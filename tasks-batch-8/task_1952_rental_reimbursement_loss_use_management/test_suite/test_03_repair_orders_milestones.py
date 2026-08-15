"""Repair orders and the milestone delay cascade."""
import pytest

from test_helpers import (
    ADJUSTER,
    ApiErrorId,
    DEFAULT_LOGICAL_CLOCK,
    ReservationStatus,
    add_approved_repair_order,
    add_repair_order_in_progress,
    api_client,
    assert_repair_milestone,
    assert_timestamp_matches_clock,
    complete_repair_order,
    create_milestone_payload,
    create_repair_order,
    get_repair_order_view,
    get_reservation_view,
    list_claim_communications,
    make_repair_shop_headers,
    open_claim,
    register_policyholder,
    register_repair_shop,
    report_delay,
    report_milestone,
    set_clock,
    setup_active_rental_scenario,
    setup_verified_claim_context,
    validate_error,
    validate_success,
)


class TestRepairOrderTransitions:
    def test_repair_order_complete_from_approved_rejected(self, api):
        """PRD §3.3: "Completing the work, again by the owning shop only, moves
        `IN_PROGRESS` to `COMPLETED` and stamps `actual_completion_date` from the
        logical clock — until then it is null."
        PRD §2.7: "the target entity's transition-level state preconditions (rung
        8, the state-error family — `ERR_VERIFICATION_ALREADY_DECIDED`,
        `ERR_RESERVATION_INVALID_STATE`, `ERR_REPAIR_ORDER_INVALID_STATE` ..."

        Design: Corner/state_machines/repair_order_complete_from_approved_rejected
        """
        policyholder = register_policyholder()
        shop = register_repair_shop()
        claim = open_claim(policyholder["id"])
        order = create_repair_order(claim["id"], shop["id"])
        resp = api.approve_repair_order(order["id"], ADJUSTER)
        validate_success(resp, 200)

        resp = api.complete_repair_order(order["id"], make_repair_shop_headers(shop["id"]))
        validate_error(resp, ApiErrorId.ERR_REPAIR_ORDER_INVALID_STATE)

    def test_milestone_on_approved_order_rejected(self, api):
        """PRD §3.3: "Reporting a milestone on an order that is not `IN_PROGRESS`
        fails with `ERR_REPAIR_ORDER_INVALID_STATE`, and a shop reporting on
        another shop's order fails with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/state_machines/milestone_on_approved_order_rejected
        """
        ctx = setup_verified_claim_context()
        add_approved_repair_order(ctx)
        resp = api.create_milestone(
            ctx["repair_order"]["id"],
            create_milestone_payload("PARTS_DELAYED"),
            make_repair_shop_headers(ctx["shop"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPAIR_ORDER_INVALID_STATE)

    def test_shop_cannot_start_other_shops_order_forbidden(self, api):
        """PRD §2.9: "A `RepairShop` caller may act only on repair orders it owns —
        starting repairs, completing repairs, and reporting milestones all require
        the order's `shop_id` to equal the caller's `X-User-ID`."
        PRD §2.9: "Every ownership failure is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/shop_cannot_start_other_shops_order_forbidden
        """
        policyholder = register_policyholder()
        shop_a = register_repair_shop(shop_name="Ace Auto Body", shop_code="SHOP-A")
        shop_b = register_repair_shop(shop_name="Bob's Body", shop_code="SHOP-B")
        claim = open_claim(policyholder["id"])
        order = create_repair_order(claim["id"], shop_a["id"])
        resp = api.approve_repair_order(order["id"], ADJUSTER)
        validate_success(resp, 200)

        resp = api.start_repair_order(order["id"], make_repair_shop_headers(shop_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        order_view = get_repair_order_view(order["id"])
        assert order_view["status"] == "APPROVED", (
            f"Order must remain APPROVED after a foreign start attempt, "
            f"got {order_view['status']}"
        )


class TestMilestoneShape:
    def test_invalid_delay_rejected(self, api):
        """PRD §3.3: "it must carry a `new_estimated_completion_date` — omitting it
        is `ERR_INVALID_REQUEST` — and that date must be strictly later than the
        order's current `estimated_completion_date`, else the report is rejected
        with `ERR_INVALID_DELAY`."

        Design: Corner/validations/invalid_delay_rejected
        """
        ctx = setup_verified_claim_context()
        add_repair_order_in_progress(ctx, estimated_completion_date="2026-08-14")

        # Earlier (not strictly later) date arm.
        earlier = api.create_milestone(
            ctx["repair_order"]["id"],
            create_milestone_payload("DELAY_REPORTED",
                                     new_estimated_completion_date="2026-08-10"),
            make_repair_shop_headers(ctx["shop"]["id"]),
        )
        validate_error(earlier, ApiErrorId.ERR_INVALID_DELAY)

        # Missing date arm.
        missing = api.create_milestone(
            ctx["repair_order"]["id"],
            create_milestone_payload("DELAY_REPORTED"),
            make_repair_shop_headers(ctx["shop"]["id"]),
        )
        validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

    def test_milestone_immutable_record_has_no_version(self, api):
        """PRD §2.5: "Three record types are deliberately append-only and carry a
        reduced property set: a repair milestone, a class change record, and a
        communication log entry each expose `id` and `created_at` only. Both
        `updated_at` and `version` are absent from these three resources, because
        they are never modified after being persisted."
        PRD §2.4: "Before any call is made, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time."

        Design: Corner/entities/milestone_immutable_record_has_no_version
        """
        ctx = setup_verified_claim_context()
        add_repair_order_in_progress(ctx, estimated_completion_date="2026-08-14")

        resp = api.create_milestone(
            ctx["repair_order"]["id"],
            create_milestone_payload("PARTS_DELAYED", note="bumper on backorder"),
            make_repair_shop_headers(ctx["shop"]["id"]),
        )
        milestone = validate_success(resp, 201)
        assert_repair_milestone(milestone)
        assert_timestamp_matches_clock(milestone["reported_at"], DEFAULT_LOGICAL_CLOCK)


class TestDelayMilestoneCascade:
    def test_delay_report_advances_estimate_and_flips_reservation(self, api):
        """PRD §3.3: "Accepting a delay report fires a three-hop cascade. First,
        the repair order's `estimated_completion_date` is advanced to the reported
        date and the order's `version` increments. Second, the reservation whose
        `repair_order_id` is this order and whose status is `ACTIVE` is flipped to
        `EXTENSION_REVIEW`, with its `version` incremented — the desk is told, in
        effect, that the authorized window no longer matches the repair reality."

        Design: Difficulty/transitive_cascade/delay_milestone_three_hop_cascade
        """
        ctx = setup_active_rental_scenario()
        set_clock("2026-08-13T09:00:00Z")

        resp = api.create_milestone(
            ctx["repair_order"]["id"],
            create_milestone_payload("DELAY_REPORTED",
                                     new_estimated_completion_date="2026-08-18",
                                     note="frame parts backordered"),
            make_repair_shop_headers(ctx["shop"]["id"]),
        )
        milestone = validate_success(resp, 201)
        assert_repair_milestone(milestone)
        assert_timestamp_matches_clock(milestone["reported_at"], "2026-08-13T09:00:00Z")

        order = get_repair_order_view(ctx["repair_order"]["id"])
        assert order["estimated_completion_date"] == "2026-08-18", (
            f"Hop 1 failed: expected estimate 2026-08-18, "
            f"got {order['estimated_completion_date']}"
        )
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["status"] == ReservationStatus.EXTENSION_REVIEW.value, (
            f"Hop 2 failed: expected EXTENSION_REVIEW, got {reservation['status']}"
        )

    def test_delay_report_logs_expectation_set(self, api):
        """PRD §3.3: "Third, a customer communication is auto-created on the claim
        with template `EXPECTATION_SET`, channel `EMAIL`, and a system-generated
        `body_summary`, so the claimant hears about the slipped timeline from the
        desk rather than from the rental counter."

        Design: Difficulty/transitive_cascade/delay_milestone_three_hop_cascade
        """
        ctx = setup_active_rental_scenario()
        set_clock("2026-08-13T09:00:00Z")

        report_delay(ctx["repair_order"]["id"], ctx["shop"]["id"], "2026-08-18",
                     note="frame parts backordered")

        logs = list_claim_communications(ctx["claim"]["id"])
        assert len(logs) == 1, (
            f"Hop 3 failed: expected exactly 1 communication entry, got {len(logs)}"
        )
        assert logs[0]["template"] == "EXPECTATION_SET"
        assert logs[0]["channel"] == "EMAIL"
        assert logs[0]["claim_id"] == ctx["claim"]["id"]
