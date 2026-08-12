"""Parts resupply: cadence variants, eligibility windows, caps, rollback, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_resupply_order_payload,
    create_shipment_payload,
    get_success_data,
    make_member_headers,
    set_clock,
    setup_delivered_with_schedule,
    validate_error,
    validate_success,
)


class TestCadenceVariants:
    def test_rolling_cadence_reanchors_on_fulfillment(self, api, care_coordinator_headers):
        """PRD §3.5: "Under `ROLLING`, each fulfillment re-anchors the cadence:
        `next_eligible_date` is `last_fulfilled_date` plus `frequency_days`. A late
        fulfillment pushes the whole cadence out."

        Design: Difficulty/dual_variant_calc/rolling_vs_calendar_anchored_resupply_cadence
        """
        ctx = setup_delivered_with_schedule(
            policy_overrides={"schedule_mode": "ROLLING", "resupply_frequency_days": 90}
        )
        # First eligibility: 2026-05-01 + 90 = 2026-07-30; fulfill off-cadence at 08-10.
        set_clock("2026-08-10T00:00:00Z")
        ro = validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        assert ro["status"] == "APPROVED"

        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["last_fulfilled_date"] == "2026-08-10"
        # ROLLING re-anchors: 2026-08-10 + 90 = 2026-11-08.
        assert schedule["next_eligible_date"] == "2026-11-08"

    def test_calendar_anchored_cadence_snaps_to_next_anchor(self, api, care_coordinator_headers):
        """PRD §3.5: "Under `CALENDAR_ANCHORED`, eligibility instants are fixed to the
        delivery anchor at whole multiples of `frequency_days`; the `next_eligible_date` is
        the smallest such instant strictly later than `last_fulfilled_date`. An off-cadence
        fulfillment snaps forward to the next anchor instant, so the same fulfillment date
        can yield a different next eligibility than `ROLLING` would."

        Design: Difficulty/dual_variant_calc/rolling_vs_calendar_anchored_resupply_cadence
        """
        ctx = setup_delivered_with_schedule(
            policy_overrides={"schedule_mode": "CALENDAR_ANCHORED",
                              "resupply_frequency_days": 90}
        )
        set_clock("2026-08-10T00:00:00Z")
        validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["last_fulfilled_date"] == "2026-08-10"
        # Anchor instants: 2026-07-30, 2026-10-28; smallest strictly > 2026-08-10.
        assert schedule["next_eligible_date"] == "2026-10-28"


class TestEligibilityWindow:
    def test_order_exactly_on_eligible_date_allowed(self, api):
        """PRD §3.5: "the current date must have reached `next_eligible_date` — inclusive,
        so ordering exactly on the eligible date is allowed, and earlier attempts fail with
        `ERR_RESUPPLY_WINDOW_NOT_OPEN`".

        Design: Difficulty/boundary_precision_check/resupply_window_equality_boundary
        """
        ctx = setup_delivered_with_schedule()
        assert ctx["schedule"]["next_eligible_date"] == "2026-07-30"
        set_clock("2026-07-30T00:00:00Z")

        ro = validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                make_member_headers(ctx["member"]["id"]),
            ), 201
        )
        assert ro["status"] == "APPROVED"
        assert ro["fulfilled_date"] == "2026-07-30"

    def test_eligible_date_fulfillment_advances_schedule(self, api, care_coordinator_headers):
        """PRD §3.5: "Its `fulfilled_date` is its creation date, which counts as the
        fulfillment for pacing purposes: the schedule's `last_fulfilled_date` is set to the
        current date, `next_eligible_date` is recomputed, and the schedule's `version`
        advances."

        Design: Difficulty/boundary_precision_check/resupply_window_equality_boundary
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2026-07-30T00:00:00Z")
        validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["last_fulfilled_date"] == "2026-07-30"
        # ROLLING: 2026-07-30 + 90 = 2026-10-28.
        assert schedule["next_eligible_date"] == "2026-10-28"

    def test_second_order_inside_gap_rejected(self, api, care_coordinator_headers):
        """PRD §3.5: "earlier attempts fail with `ERR_RESUPPLY_WINDOW_NOT_OPEN`" — a second
        order one instant after a fulfillment has not reached the recomputed
        `next_eligible_date`.

        Design: Difficulty/resource_temporal_overlap/resupply_minimum_gap_buffer
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2026-07-30T00:00:00Z")
        validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        res = api.create_resupply_order(
            create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_RESUPPLY_WINDOW_NOT_OPEN, expected_status=422)

    def test_gap_rejection_leaves_schedule_pacing_unchanged(self, api, care_coordinator_headers):
        """PRD §3.5: "the schedule's `last_fulfilled_date` is set to the current date,
        `next_eligible_date` is recomputed" — only successful creations touch the pacing
        state.

        Design: Difficulty/resource_temporal_overlap/resupply_minimum_gap_buffer
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2026-07-30T00:00:00Z")
        ro1 = validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        api.create_resupply_order(
            create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
            care_coordinator_headers,
        )
        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["last_fulfilled_date"] == "2026-07-30"
        assert schedule["next_eligible_date"] == "2026-10-28"
        ro1_after = validate_success(
            api.get_resupply_order(ro1["id"], care_coordinator_headers), 200
        )
        assert ro1_after["status"] == "APPROVED"


class TestResupplyOrderComputation:
    def test_resupply_order_snapshots_price_and_computes_total(self, api,
                                                               care_coordinator_headers):
        """PRD §3.5: "A resupply order is born in `APPROVED` — there is no separate
        approval step — with `unit_price_cents` snapshotted from the part and `total_cents`
        equal to quantity times unit price, rounded half up."

        Design: Corner/calculations/resupply_total_cents_computed
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2026-07-30T00:00:00Z")
        ro = validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 3),
                care_coordinator_headers,
            ), 201
        )
        assert ro["unit_price_cents"] == 500
        assert ro["total_cents"] == 1500
        assert ro["status"] == "APPROVED"


class TestResupplyGuards:
    def test_quantity_over_part_cap_rejected(self, api, care_coordinator_headers):
        """PRD §3.5: "The requested `quantity` must not exceed the part's
        `max_qty_per_frequency` (`ERR_RESUPPLY_QUANTITY_CAP_EXCEEDED`)."

        Design: Corner/validations/quantity_cap_exceeded_on_resupply
        """
        ctx = setup_delivered_with_schedule()  # part max_qty_per_frequency 4
        set_clock("2026-07-30T00:00:00Z")
        res = api.create_resupply_order(
            create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 5),
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_RESUPPLY_QUANTITY_CAP_EXCEEDED,
                       expected_status=422)
        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["last_fulfilled_date"] is None

    def test_suspended_schedule_rejects_resupply(self, api, care_coordinator_headers):
        """PRD §3.5: "the schedule must be `ACTIVE` (`ERR_SCHEDULE_NOT_ACTIVE` otherwise)".

        Design: Corner/validations/schedule_not_active_blocks_resupply
        """
        ctx = setup_delivered_with_schedule()
        schedule = ctx["schedule"]
        validate_success(
            api.patch_resupply_schedule(
                schedule["id"],
                {"status": "SUSPENDED",
                 "expected_schedule_version": schedule["version"]},
                care_coordinator_headers,
            ), 200
        )
        set_clock("2026-07-30T00:00:00Z")
        res = api.create_resupply_order(
            create_resupply_order_payload(schedule["id"], ctx["member"]["id"], 1),
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_SCHEDULE_NOT_ACTIVE, expected_status=409)

        schedule_after = validate_success(
            api.get_resupply_schedule(schedule["id"], care_coordinator_headers), 200
        )
        assert schedule_after["status"] == "SUSPENDED"

    def test_resupply_after_benefit_period_end_ends_schedule(self, api,
                                                             care_coordinator_headers):
        """PRD §3.5: "That last check is lazy: if the current date has reached the policy's
        `benefit_period_end`, the schedule transitions `ACTIVE → ENDED`, the member's
        aggregates are recomputed, and the call is rejected with
        `ERR_BENEFIT_PERIOD_ENDED`."

        Design: Corner/validations/benefit_period_ended_blocks_resupply_and_ends_schedule
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2027-01-01T00:00:00Z")  # == benefit_period_end (half-open, exclusive)
        res = api.create_resupply_order(
            create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_BENEFIT_PERIOD_ENDED, expected_status=422)

    def test_benefit_period_lazy_end_recomputes_member_aggregates(self, api,
                                                                  care_coordinator_headers):
        """PRD §3.5: "the schedule transitions `ACTIVE → ENDED`, the member's aggregates
        are recomputed, and the call is rejected with `ERR_BENEFIT_PERIOD_ENDED`."

        Design: Corner/validations/benefit_period_ended_blocks_resupply_and_ends_schedule
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2027-01-01T00:00:00Z")
        api.create_resupply_order(
            create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
            care_coordinator_headers,
        )
        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["status"] == "ENDED"
        member = validate_success(
            api.get_member(ctx["member"]["id"], care_coordinator_headers), 200
        )
        assert member["active_schedule_count"] == 0


class TestResupplyCancellation:
    def test_cancel_approved_resupply_rolls_back_schedule(self, api, care_coordinator_headers):
        """PRD §3.5: "Cancelling an `APPROVED` resupply order moves it to `CANCELLED` and
        repairs the pacing state: if the schedule's `last_fulfilled_date` equals this
        order's `fulfilled_date`, it rolls back to the `fulfilled_date` of the latest other
        non-`CANCELLED` resupply order on that schedule — or null if none remains — and
        `next_eligible_date` is recomputed."

        Design: Corner/state_machines/resupply_cancel_rolls_back_schedule
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2026-07-30T00:00:00Z")
        ro = validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        cancelled = validate_success(
            api.cancel_resupply_order(ro["id"], care_coordinator_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"

        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["last_fulfilled_date"] is None
        assert schedule["next_eligible_date"] == "2026-07-30"

    def test_cancel_delivered_resupply_order_rejected(self, api, care_coordinator_headers,
                                                      warehouse_operator_headers):
        """PRD §3.5: "Once a resupply order has shipped it can no longer be cancelled;
        `DELIVERED` and `CANCELLED` are terminal."

        Design: Corner/state_machines/cancel_delivered_resupply_order_rejected
        """
        ctx = setup_delivered_with_schedule()
        set_clock("2026-07-30T00:00:00Z")
        ro = validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        rsh = validate_success(
            api.create_shipment(
                create_shipment_payload(resupply_order_id=ro["id"], tracking_number="1Z-O2"),
                warehouse_operator_headers,
            ), 201
        )
        for target in ("IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"):
            rsh = validate_success(
                api.advance_shipment(rsh["id"], {"to_status": target},
                                     warehouse_operator_headers), 200
            )
        res = api.cancel_resupply_order(ro["id"], care_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        ro_after = validate_success(
            api.get_resupply_order(ro["id"], care_coordinator_headers), 200
        )
        assert ro_after["status"] == "DELIVERED"


class TestScheduleOcc:
    def test_stale_schedule_version_rejected_after_resupply_order(
        self, api, care_coordinator_headers
    ):
        """PRD §2.4: "Adjusting a resupply schedule requires `expected_schedule_version`,
        carrying the `version` of the `ResupplySchedule` the client last observed. A
        resupply order created or cancelled in the meantime mutates the schedule and bumps
        its `version`, so a writer holding an old `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_schedule_patch
        """
        ctx = setup_delivered_with_schedule()
        observed_version = ctx["schedule"]["version"]
        set_clock("2026-07-30T00:00:00Z")
        # Creating a resupply order bumps the schedule version behind the client's back.
        validate_success(
            api.create_resupply_order(
                create_resupply_order_payload(ctx["schedule"]["id"], ctx["member"]["id"], 1),
                care_coordinator_headers,
            ), 201
        )
        res = api.patch_resupply_schedule(
            ctx["schedule"]["id"],
            {"frequency_days": 60, "expected_schedule_version": observed_version},
            care_coordinator_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        schedule = validate_success(
            api.get_resupply_schedule(ctx["schedule"]["id"], care_coordinator_headers), 200
        )
        assert schedule["frequency_days"] == 90
