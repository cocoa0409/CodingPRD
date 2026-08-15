"""Extension requests: the ACTIVE <-> EXTENSION_REVIEW loop, the pinned day-grant
evaluation order, cap boundaries, precedence, and OCC."""
import pytest

from test_helpers import (
    ADJUSTER,
    DESK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_repair_order_in_progress,
    api_client,
    assert_extension_request,
    authorize_reservation,
    book_reservation,
    cancel_reservation,
    complete_repair_order,
    create_extension_request_payload,
    get_claim_view,
    get_extension_view,
    get_reservation_view,
    report_delay,
    request_extension,
    set_clock,
    setup_active_rental_scenario,
    setup_pending_extension_scenario,
    setup_verified_claim_context,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestExtensionGateFailures:
    def test_extension_not_justified_rejected(self, api):
        """PRD §3.5: "When the count is zero — the milestone's new estimate plus
        the grace day does not reach beyond the current authorized window — the
        approval fails with `ERR_EXTENSION_NOT_JUSTIFIED`."

        Design: Corner/validations/extension_not_justified_rejected
        """
        ctx = setup_pending_extension_scenario(
            new_estimated_completion_date="2026-08-16",
            requested_additional_days=3,
            reservation_overrides={"authorized_return_date": "2026-08-20"},
        )
        resp = api.approve_extension_request(ctx["extension"]["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_JUSTIFIED)

    def test_milestone_not_found_rejected(self, api):
        """PRD §2.8: "The same codes apply when a body-referenced identifier does
        not exist — creating a reservation against a missing repair order fails
        with `ERR_REPAIR_ORDER_NOT_FOUND`, and creating an extension request
        against a missing milestone fails with `ERR_MILESTONE_NOT_FOUND`."

        Design: Corner/errors/milestone_not_found_rejected
        """
        ctx = setup_active_rental_scenario()
        reservation = get_reservation_view(ctx["reservation"]["id"])
        resp = api.create_extension_request(
            create_extension_request_payload(
                ctx["reservation"]["id"], NON_EXISTENT_UUID, 2,
                reservation["version"]),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_FOUND)

    def test_extension_request_not_found_rejected(self, api):
        """PRD §2.8: "Each resource type has its own not-found error:
        `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_COVERAGE_VERIFICATION_NOT_FOUND`, `ERR_REPAIR_SHOP_NOT_FOUND`,
        `ERR_RENTAL_PARTNER_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`,
        `ERR_MILESTONE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_EXTENSION_REQUEST_NOT_FOUND`, `ERR_LOSS_OF_USE_CLAIM_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, and `ERR_RECOVERY_CASE_NOT_FOUND`."

        Design: Corner/errors/extension_request_not_found_rejected
        """
        resp = api.approve_extension_request(NON_EXISTENT_UUID, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_REQUEST_NOT_FOUND)


class TestExtensionOptimisticConcurrency:
    def test_extension_request_stale_reservation_version_rejected(self, api):
        """PRD §2.10: "Creating an extension request supersedes any submitted
        request on the reservation and flips the reservation into review, so the
        creation request must carry `expected_reservation_version`, the
        reservation `version` the client last observed. A mismatch with the
        reservation's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from pushing a reservation it has not
        re-read into review."
        PRD §3.5: "Any earlier still-`SUBMITTED` request on the same reservation
        is automatically moved to `SUPERSEDED`, so at most one request per
        reservation is ever awaiting a decision."

        Design: Corner/cross_cutting_complexity/extension_request_stale_reservation_version_rejected
        """
        ctx = setup_active_rental_scenario()
        milestone = report_delay(ctx["repair_order"]["id"], ctx["shop"]["id"],
                                 "2026-08-18")
        stale_version = get_reservation_view(ctx["reservation"]["id"])["version"]

        first = request_extension(ctx["reservation"]["id"], milestone["id"], 3,
                                  expected_reservation_version=stale_version)

        stale = api.create_extension_request(
            create_extension_request_payload(
                ctx["reservation"]["id"], milestone["id"], 5, stale_version),
            DESK,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_reservation_view(ctx["reservation"]["id"])["version"]
        second_resp = api.create_extension_request(
            create_extension_request_payload(
                ctx["reservation"]["id"], milestone["id"], 5, fresh_version),
            DESK,
        )
        second = validate_success(second_resp, 201)
        assert_extension_request(second)

        listed, meta = validate_paginated(api.list_reservation_extension_requests(
            ctx["reservation"]["id"], DESK))
        assert meta["total_count"] == 2
        by_id = {e["id"]: e for e in listed}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "SUBMITTED"


class TestExtensionGrantPinnedOrder:
    def _setup_grant_scenario(self):
        return setup_pending_extension_scenario(
            new_estimated_completion_date="2026-08-18",
            requested_additional_days=10,
            delay_clock="2026-08-13T09:00:00Z",
        )

    def test_extension_grant_uses_pregrant_values(self, api):
        """PRD §3.5: "Approval is the adjuster's call, and the day grant is
        computed in a pinned evaluation order using only pre-grant values."
        PRD §3.5: "Third, `granted_days` is the smallest of the requested
        additional days, the cap headroom, and the justified need"

        Design: Difficulty/combinatorial_formula/extension_grant_circular_order_pinned
        """
        ctx = self._setup_grant_scenario()
        resp = api.approve_extension_request(ctx["extension"]["id"], ADJUSTER)
        approved = validate_success(resp, 200)
        assert approved["granted_days"] == 4, (
            f"Expected granted_days min(10, 10, 4) == 4 under the pinned "
            f"pre-grant order, got {approved['granted_days']}"
        )

    def test_extension_grant_applied_exactly_once(self, api):
        """PRD §3.5: "An approved grant is applied exactly once: the
        `authorized_return_date` moves later by `granted_days`, `authorized_days`
        grows by the same amount, the provisional `estimated_charge_cents` grows
        by `granted_days` times the `daily_rate_cents`, and the claim's
        `rental_reserve_cents` falls by that same cost, with the claim's `version`
        incrementing. The reservation returns to `ACTIVE` with its `version`
        incremented, the request lands in `APPROVED`, and a customer communication
        with template `EXTENSION_UPDATE` is logged on the claim."

        Design: Difficulty/combinatorial_formula/extension_grant_circular_order_pinned
        """
        ctx = self._setup_grant_scenario()
        validate_success(
            api.approve_extension_request(ctx["extension"]["id"], ADJUSTER), 200)
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["authorized_return_date"] == "2026-08-19"
        assert reservation["authorized_days"] == 14
        assert reservation["estimated_charge_cents"] == 84000, (
            f"Expected 60000 + 4 x 6000 = 84000, "
            f"got {reservation['estimated_charge_cents']}"
        )
        assert reservation["status"] == "ACTIVE", (
            "The EXTENSION_REVIEW loop must close back to ACTIVE after approval"
        )
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["rental_reserve_cents"] == 36000, (
            f"Expected reserve 120000 - 60000 - 24000 = 36000, "
            f"got {claim['rental_reserve_cents']}"
        )


class TestExtensionReviewCycle:
    def test_extension_denial_returns_reservation_active_unchanged(self, api):
        """PRD §3.5: "The reservation must be `ACTIVE` or already under review:
        creating the request flips an `ACTIVE` reservation to `EXTENSION_REVIEW`
        (a reservation already in `EXTENSION_REVIEW` stays there) and increments
        the reservation's `version`, while requesting an extension on a terminal
        reservation fails with `ERR_RESERVATION_INVALID_STATE`."
        PRD §3.5: "the request lands in `DENIED`, the reservation returns to
        `ACTIVE` with its `version` incremented but its window unchanged, and the
        same `EXTENSION_UPDATE` communication goes out — but unlike an approval,
        a denial does not advance the claim's `version`."

        Design: Difficulty/non_linear_state_machine/reservation_extension_review_cycle
        """
        ctx = setup_pending_extension_scenario(
            new_estimated_completion_date="2026-08-18",
            requested_additional_days=5,
            delay_clock="2026-08-12T09:00:00Z",
        )
        assert ctx["reservation"]["status"] == "EXTENSION_REVIEW"

        resp = api.deny_extension_request(
            ctx["extension"]["id"], {"decision_reason": "customer declined"}, ADJUSTER)
        denied = validate_success(resp, 200)
        assert denied["status"] == "DENIED"
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["status"] == "ACTIVE", (
            "First loop must close back to ACTIVE after the denial"
        )
        assert reservation["authorized_days"] == 10, (
            "A denial grants nothing: authorized_days must stay 10"
        )

    def test_extension_cycle_reenters_and_grants(self, api):
        """PRD §3.5: "creating the request flips an `ACTIVE` reservation to
        `EXTENSION_REVIEW` (a reservation already in `EXTENSION_REVIEW` stays
        there)"
        PRD §3.5: "Third, `granted_days` is the smallest of the requested
        additional days, the cap headroom, and the justified need"

        Design: Difficulty/non_linear_state_machine/reservation_extension_review_cycle
        """
        ctx = setup_pending_extension_scenario(
            new_estimated_completion_date="2026-08-18",
            requested_additional_days=5,
            delay_clock="2026-08-12T09:00:00Z",
        )
        first = ctx["extension"]
        validate_success(api.deny_extension_request(
            first["id"], {"decision_reason": "customer declined"}, ADJUSTER), 200)

        # Second loop: the cycle re-enters EXTENSION_REVIEW from ACTIVE.
        milestone2 = report_delay(ctx["repair_order"]["id"], ctx["shop"]["id"],
                                  "2026-08-20")
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["status"] == "EXTENSION_REVIEW", (
            "The cycle must re-enter EXTENSION_REVIEW on the second delay report"
        )
        second = request_extension(ctx["reservation"]["id"], milestone2["id"], 5)

        resp = api.approve_extension_request(second["id"], ADJUSTER)
        approved = validate_success(resp, 200)
        assert approved["granted_days"] == 5, (
            f"Expected min(5, 10, 6) == 5, got {approved['granted_days']}"
        )
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["authorized_days"] == 15
        assert reservation["authorized_return_date"] == "2026-08-20"
        assert reservation["estimated_charge_cents"] == 90000
        assert reservation["status"] == "ACTIVE"
        assert get_extension_view(first["id"])["status"] == "DENIED"
        assert get_extension_view(second["id"])["status"] == "APPROVED"


class TestExtensionCapBoundary:
    def _setup_cap_scenario(self):
        return setup_pending_extension_scenario(
            new_estimated_completion_date="2026-08-25",
            requested_additional_days=10,
        )

    def test_grant_landing_exactly_at_cap_succeeds(self, api):
        """PRD §2.6: "The `authorized_days_total` ledger sums `authorized_days`
        over the claim's reservations in `AUTHORIZED`, `ACTIVE`,
        `EXTENSION_REVIEW`, or `RETURNED` status. It is the yardstick for the
        duration cap: the total may never exceed the claim's
        `coverage_duration_cap_days`."

        Design: Difficulty/boundary_precision_check/extension_grant_at_cap_exactly
        """
        ctx = self._setup_cap_scenario()
        resp = api.approve_extension_request(ctx["extension"]["id"], ADJUSTER)
        approved = validate_success(resp, 200)
        assert approved["granted_days"] == 10, (
            f"Grant landing exactly at the cap must be allowed; "
            f"got granted_days {approved['granted_days']}"
        )
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["authorized_days_total"] == 20 == claim["coverage_duration_cap_days"]

    def test_extension_create_with_zero_cap_headroom_rejected(self, api):
        """PRD §3.5: "If the claim has no duration-cap headroom left — authorized
        days already total the cap — creation is refused with
        `ERR_DURATION_CAP_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/extension_grant_at_cap_exactly
        """
        ctx = self._setup_cap_scenario()
        validate_success(
            api.approve_extension_request(ctx["extension"]["id"], ADJUSTER), 200)

        milestone2 = report_delay(ctx["repair_order"]["id"], ctx["shop"]["id"],
                                  "2026-08-30")
        reservation = get_reservation_view(ctx["reservation"]["id"])
        resp = api.create_extension_request(
            create_extension_request_payload(
                ctx["reservation"]["id"], milestone2["id"], 1,
                reservation["version"]),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_DURATION_CAP_EXHAUSTED)


class TestExtensionPrecedence:
    def _setup_state_vs_fiscal_scenario(self):
        """R1 consumes the whole 20-day cap; R2 (back-to-back) is cancelled; a
        delay milestone exists on the shared IN_PROGRESS repair order."""
        ctx = setup_verified_claim_context(
            partner_overrides={"standard_capacity": 2})
        add_repair_order_in_progress(ctx, estimated_completion_date="2026-08-24",
                                     labor_hours_estimate=40)
        r1 = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                              ctx["repair_order"]["id"],
                              pickup_date="2026-08-05",
                              authorized_return_date="2026-08-25")
        authorize_reservation(r1["id"])
        r2 = book_reservation(ctx["claim"]["id"], ctx["partner"]["id"],
                              ctx["repair_order"]["id"],
                              pickup_date="2026-08-25",
                              authorized_return_date="2026-08-26")
        cancel_reservation(r2["id"])
        milestone = report_delay(ctx["repair_order"]["id"], ctx["shop"]["id"],
                                 "2026-08-28")
        ctx.update(r1=r1, r2=r2, milestone=milestone)
        return ctx

    def test_state_error_beats_cap_exhausted_on_extension_create(self, api):
        """PRD §2.7: "Two precedence pairs are pinned explicitly because they are
        easy to get wrong: a state-precondition failure (rung 8) is always
        reported before a fiscal failure (rung 13), and a temporal failure (rung
        10) is always reported before a referential one (rung 11)."
        PRD §3.5: "requesting an extension on a terminal reservation fails with
        `ERR_RESERVATION_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/extension_create_state_beats_fiscal
        """
        ctx = self._setup_state_vs_fiscal_scenario()
        reservation = get_reservation_view(ctx["r2"]["id"])
        assert reservation["status"] == "CANCELLED"
        assert get_claim_view(ctx["claim"]["id"])["authorized_days_total"] == 20, (
            "Setup: R1 must consume the full 20-day cap (fiscal arm armed)"
        )
        resp = api.create_extension_request(
            create_extension_request_payload(
                ctx["r2"]["id"], ctx["milestone"]["id"], 1, reservation["version"]),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_INVALID_STATE)

    def test_failed_extension_create_persists_nothing(self, api):
        """PRD §3.5: "requesting an extension on a terminal reservation fails with
        `ERR_RESERVATION_INVALID_STATE`"
        PRD §2.7: "a state-precondition failure (rung 8) is always reported before
        a fiscal failure (rung 13)"

        Design: Difficulty/priority_pair_validation_conflict/extension_create_state_beats_fiscal
        """
        ctx = self._setup_state_vs_fiscal_scenario()
        reservation = get_reservation_view(ctx["r2"]["id"])
        api.create_extension_request(
            create_extension_request_payload(
                ctx["r2"]["id"], ctx["milestone"]["id"], 1, reservation["version"]),
            DESK,
        )
        _, meta = validate_paginated(api.list_reservation_extension_requests(
            ctx["r2"]["id"], DESK))
        assert meta["total_count"] == 0, (
            "A rejected extension create must not persist any request"
        )


class TestExtensionRepairOrderGate:
    def _setup_completed_before_decision(self):
        ctx = setup_pending_extension_scenario(
            new_estimated_completion_date="2026-08-18", requested_additional_days=4)
        complete_repair_order(ctx["repair_order"]["id"], ctx["shop"]["id"])
        return ctx

    def test_extension_approve_rejected_after_repair_completed(self, api):
        """PRD §3.5: "the approval requires the reservation to be in
        `EXTENSION_REVIEW` (`ERR_RESERVATION_INVALID_STATE` otherwise), the
        request itself to be `SUBMITTED` (`ERR_EXTENSION_INVALID_STATE`
        otherwise), and the repair order to be `IN_PROGRESS`
        (`ERR_REPAIR_ORDER_INVALID_STATE` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/extension_approve_requires_repair_in_progress
        """
        ctx = self._setup_completed_before_decision()
        resp = api.approve_extension_request(ctx["extension"]["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_REPAIR_ORDER_INVALID_STATE)

    def test_failed_approve_leaves_extension_pending(self, api):
        """PRD §3.5: "the approval requires the reservation to be in
        `EXTENSION_REVIEW` (`ERR_RESERVATION_INVALID_STATE` otherwise), the
        request itself to be `SUBMITTED` (`ERR_EXTENSION_INVALID_STATE`
        otherwise), and the repair order to be `IN_PROGRESS`
        (`ERR_REPAIR_ORDER_INVALID_STATE` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/extension_approve_requires_repair_in_progress
        """
        ctx = self._setup_completed_before_decision()
        api.approve_extension_request(ctx["extension"]["id"], ADJUSTER)
        assert get_extension_view(ctx["extension"]["id"])["status"] == "SUBMITTED"
        assert get_reservation_view(ctx["reservation"]["id"])["status"] == (
            "EXTENSION_REVIEW"
        )
