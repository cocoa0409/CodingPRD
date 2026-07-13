"""Media plans, the insertion-order budget ledger, flight conflicts and delivery figures."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_campaign,
    assert_insertion_order,
    assert_media_budget_conserved,
    assert_media_plan,
    create_insertion_order_payload,
    deliver_insertion_order,
    log_and_approve_time,
    media_plan_version,
    place_insertion_order,
    register_placement,
    reserve_insertion_order,
    setup_base,
    setup_media_plan,
    validate_error,
    validate_success,
)


class TestPlaceRequiresAnApprovedPlan:
    """Difficulty: cross_entity_state_dependency / insertion_order_place_gated_by_unapproved_media_plan."""

    @staticmethod
    def _setup():
        base = setup_base()
        placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
        plan = setup_media_plan(base, approved_budget_cents=10_000_000, allowed_channels=["VIDEO"])
        order = reserve_insertion_order(
            base, plan["id"], placement["id"], flight_start="2026-06-05",
            flight_end="2026-06-20", gross_cents=1_000_000,
        )
        base.update({"placement": placement, "plan": plan, "order": order})
        return base

    def test_placing_an_order_on_a_draft_plan_is_rejected(self, api):
        """PRD §3.7: "From `RESERVED` the buyer sends the order to the publisher,
        `RESERVED → PLACED`, which is legal only when the owning plan is `APPROVED` — a plan
        still in `DRAFT`, or already `LOCKED`, is rejected with `ERR_MEDIA_PLAN_NOT_APPROVED`."
        PRD §2.8: "The cross-entity state gate on the governing media plan: sending an insertion
        order to the publisher requires the plan to be `APPROVED` — otherwise
        `ERR_MEDIA_PLAN_NOT_APPROVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/insertion_order_place_gated_by_unapproved_media_plan
        """
        base = self._setup()

        resp = api.place_insertion_order(base["order"]["id"], base["mia_headers"])
        validate_error(resp, ApiErrorId.ERR_MEDIA_PLAN_NOT_APPROVED.value)
        assert resp.status_code == 409

        order = validate_success(api.get_insertion_order(base["order"]["id"], base["mia_headers"]))
        assert order["status"] == "RESERVED", "the rejected place must leave the order untouched"

    def test_the_same_place_call_succeeds_once_the_plan_is_approved(self, api):
        """PRD §3.7: "The advertiser's `ClientReviewer` signs the plan off — legal only from
        `DRAFT`, only on a campaign that is `IN_FLIGHT`, and only when `X-User-ID` matches that
        campaign's advertiser — moving it `DRAFT → APPROVED`."
        PRD §3.7: "An accepted order is created in `RESERVED`, and the plan's
        `uncommitted_cents` is reduced by the order's `gross_cents`; the plan's `version` moves
        with it. From `RESERVED` the buyer sends the order to the publisher,
        `RESERVED → PLACED`, which is legal only when the owning plan is `APPROVED` — a plan
        still in `DRAFT`, or already `LOCKED`, is rejected with `ERR_MEDIA_PLAN_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/insertion_order_place_gated_by_unapproved_media_plan
        """
        base = self._setup()

        plan = validate_success(api.approve_media_plan(base["plan"]["id"], base["reviewer_headers"]))
        assert_media_plan(plan)
        assert plan["status"] == "APPROVED"
        assert plan["uncommitted_cents"] == 9_000_000

        placed = validate_success(api.place_insertion_order(base["order"]["id"], base["mia_headers"]))
        assert_insertion_order(placed)
        assert placed["status"] == "PLACED"


class TestFlightConflictWithDarkDayBuffer:
    """Difficulty: resource_temporal_overlap /
    io_flight_closed_interval_plus_dark_day_buffer_on_placement."""

    @staticmethod
    def _setup():
        base = setup_base()
        placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=2)
        plan = setup_media_plan(base, approved_budget_cents=20_000_000, allowed_channels=["VIDEO"])
        reserve_insertion_order(
            base, plan["id"], placement["id"], flight_start="2026-06-01",
            flight_end="2026-06-10", gross_cents=1_000_000,
        )
        base.update({"placement": placement, "plan": plan})
        return base

    def test_a_single_dark_day_after_an_existing_flight_collides(self, api):
        """PRD §3.7: "The flight must not collide with another booking on the same slot: taking
        the placement's `min_dark_days` as a buffer, the new order conflicts with any other
        insertion order on the same `placement_id` whose status is `RESERVED`, `PLACED` or
        `DELIVERED` when the new flight's start falls on or before that existing flight's end
        extended forward by the dark-day buffer *and* the existing flight's start falls on or
        before the new flight's end extended forward by the same buffer. A conflict is rejected
        with `ERR_PLACEMENT_FLIGHT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/io_flight_closed_interval_plus_dark_day_buffer_on_placement
        """
        base = self._setup()
        version = media_plan_version(base["plan"]["id"], base["mia_headers"])

        resp = api.create_insertion_order(
            create_insertion_order_payload(
                base["plan"]["id"], base["placement"]["id"], version,
                flight_start="2026-06-12", flight_end="2026-06-20", gross_cents=1_000_000,
            ),
            base["mia_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_FLIGHT_CONFLICT.value)
        assert resp.status_code == 409

        plan = validate_success(api.get_media_plan(base["plan"]["id"], base["mia_headers"]))
        assert plan["uncommitted_cents"] == 19_000_000, "the rejected order committed nothing"

    def test_two_clear_dark_days_after_an_existing_flight_are_accepted(self, api):
        """PRD §3.7: "The flight must not collide with another booking on the same slot: taking
        the placement's `min_dark_days` as a buffer, the new order conflicts with any other
        insertion order on the same `placement_id` whose status is `RESERVED`, `PLACED` or
        `DELIVERED` when the new flight's start falls on or before that existing flight's end
        extended forward by the dark-day buffer *and* the existing flight's start falls on or
        before the new flight's end extended forward by the same buffer. A conflict is rejected
        with `ERR_PLACEMENT_FLIGHT_CONFLICT`."
        PRD §3.7: "The flight window is a **closed** date interval: `flight_start` is the first
        day on air and `flight_end` is the last day on air, and both days are on air;
        `flight_end` must be on or after `flight_start`, so a single-day flight has the two
        dates equal."

        Design: Difficulty/resource_temporal_overlap/io_flight_closed_interval_plus_dark_day_buffer_on_placement
        """
        base = self._setup()
        version = media_plan_version(base["plan"]["id"], base["mia_headers"])

        data = validate_success(
            api.create_insertion_order(
                create_insertion_order_payload(
                    base["plan"]["id"], base["placement"]["id"], version,
                    flight_start="2026-06-13", flight_end="2026-06-20", gross_cents=1_000_000,
                ),
                base["mia_headers"],
            ),
            201,
        )
        assert data["status"] == "RESERVED"
        assert data["flight_start"].startswith("2026-06-13")

        plan = validate_success(api.get_media_plan(base["plan"]["id"], base["mia_headers"]))
        assert plan["uncommitted_cents"] == 18_000_000


class TestMediaBudgetConservation:
    """Difficulty: compensating_invariant / media_budget_conserved_across_reserve_and_cancel."""

    @staticmethod
    def _setup():
        base = setup_base()
        placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
        plan = setup_media_plan(base, approved_budget_cents=10_000_000, allowed_channels=["VIDEO"])
        first = reserve_insertion_order(
            base, plan["id"], placement["id"], flight_start="2026-06-01",
            flight_end="2026-06-10", gross_cents=4_000_000,
        )
        base.update({"placement": placement, "plan": plan, "first": first})
        return base

    def test_reserving_inventory_commits_budget_out_of_the_plan(self, api):
        """PRD §3.7: "An accepted order is created in `RESERVED`, and the plan's
        `uncommitted_cents` is reduced by the order's `gross_cents`; the plan's `version` moves
        with it."
        PRD §3.7: "The plan is created in `DRAFT`, and its `uncommitted_cents` starts equal to
        `approved_budget_cents`."

        Design: Difficulty/compensating_invariant/media_budget_conserved_across_reserve_and_cancel
        """
        base = self._setup()

        second = reserve_insertion_order(
            base, base["plan"]["id"], base["placement"]["id"], flight_start="2026-07-01",
            flight_end="2026-07-10", gross_cents=3_000_000,
        )
        assert second["status"] == "RESERVED"

        plan = validate_success(api.get_media_plan(base["plan"]["id"], base["mia_headers"]))
        assert plan["uncommitted_cents"] == 3_000_000
        assert plan["approved_budget_cents"] == 10_000_000
        assert_media_budget_conserved(plan, [base["first"], second])

    def test_cancelling_an_order_releases_exactly_what_it_committed(self, api):
        """PRD §3.7: "Cancellation is the compensating action of creation and is legal from
        `RESERVED` and from `PLACED`. It moves the order to the terminal `CANCELLED` state and
        adds the order's `gross_cents` straight back into the plan's `uncommitted_cents`,
        incrementing both the order's and the plan's `version`."
        PRD §2.9: "**Media budget.** A media plan's `approved_budget_cents` always equals its
        `uncommitted_cents` plus the sum of `gross_cents` across every insertion order on that
        plan whose status is `RESERVED`, `PLACED` or `DELIVERED`. Cancelled orders hold no
        budget; delivered orders still do."

        Design: Difficulty/compensating_invariant/media_budget_conserved_across_reserve_and_cancel
        """
        base = self._setup()
        second = reserve_insertion_order(
            base, base["plan"]["id"], base["placement"]["id"], flight_start="2026-07-01",
            flight_end="2026-07-10", gross_cents=3_000_000,
        )

        cancelled = validate_success(api.cancel_insertion_order(second["id"], base["mia_headers"]))
        assert cancelled["status"] == "CANCELLED"

        first = validate_success(api.get_insertion_order(base["first"]["id"], base["mia_headers"]))
        assert first["status"] == "RESERVED", "the untouched order keeps holding its share"

        plan = validate_success(api.get_media_plan(base["plan"]["id"], base["mia_headers"]))
        assert plan["uncommitted_cents"] == 6_000_000
        assert_media_budget_conserved(plan, [first, cancelled])


class TestEligibilityPrecedesFlightConflict:
    """Difficulty: priority_pair_validation_conflict /
    placement_channel_referential_precedes_flight_temporal_conflict."""

    @staticmethod
    def _setup():
        base = setup_base()
        second_campaign = add_campaign(base, name="Autumn Push")
        placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
        plan_video = setup_media_plan(
            base, approved_budget_cents=10_000_000, allowed_channels=["VIDEO"])
        occupying = reserve_insertion_order(
            base, plan_video["id"], placement["id"], flight_start="2026-06-05",
            flight_end="2026-06-20", gross_cents=1_000_000,
        )
        plan_display = setup_media_plan(
            base, campaign_id=second_campaign["id"], approved_budget_cents=10_000_000,
            allowed_channels=["DISPLAY"],
        )
        base.update({"placement": placement, "plan_video": plan_video,
                     "plan_display": plan_display, "occupying": occupying})
        return base

    def test_the_channel_whitelist_error_wins_over_the_flight_conflict(self, api):
        """PRD §2.8: "When a single request violates more than one rule, the response must
        report the violation that comes first in the following ordering. This ordering is
        normative; a lower-numbered check that fails masks every higher-numbered one."
        PRD §2.8: "Referential eligibility: the publisher slot's channel must be whitelisted on
        the media plan, otherwise `ERR_PLACEMENT_NOT_ELIGIBLE` (HTTP 422); a campaign's
        statement of work must belong to the same advertiser as the campaign, and an invoice's
        campaign and retainer must both belong to the same advertiser as the invoice, otherwise
        `ERR_INVALID_REQUEST` (HTTP 400). This check guards insertion-order creation, campaign
        creation and invoice creation."
        PRD §2.8: "Interval-occupancy conflicts on insertion-order creation
        (`ERR_PLACEMENT_FLIGHT_CONFLICT`) and time-entry creation (`ERR_TIME_ENTRY_OVERLAP`),
        both HTTP 409, as specified in sections 3.5 and 3.7."

        Design: Difficulty/priority_pair_validation_conflict/placement_channel_referential_precedes_flight_temporal_conflict
        """
        base = self._setup()
        version = media_plan_version(base["plan_display"]["id"], base["mia_headers"])

        resp = api.create_insertion_order(
            create_insertion_order_payload(
                base["plan_display"]["id"], base["placement"]["id"], version,
                flight_start="2026-06-10", flight_end="2026-06-15", gross_cents=1_000_000,
            ),
            base["mia_headers"],
        )
        # The VIDEO slot is not whitelisted on the DISPLAY plan AND its flight collides with the
        # order already sitting on that same slot; the referential check must be the one reported.
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_ELIGIBLE.value)
        assert resp.status_code == 422
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_PLACEMENT_FLIGHT_CONFLICT.value

    def test_the_rejected_order_commits_no_budget_and_disturbs_no_existing_order(self, api):
        """PRD §3.7: "The slot's `channel` must be a member of the plan's `allowed_channels`, or
        the order is rejected with `ERR_PLACEMENT_NOT_ELIGIBLE`."
        PRD §3.7: "An accepted order is created in `RESERVED`, and the plan's
        `uncommitted_cents` is reduced by the order's `gross_cents`; the plan's `version` moves
        with it."

        Design: Difficulty/priority_pair_validation_conflict/placement_channel_referential_precedes_flight_temporal_conflict
        """
        base = self._setup()
        version = media_plan_version(base["plan_display"]["id"], base["mia_headers"])

        resp = api.create_insertion_order(
            create_insertion_order_payload(
                base["plan_display"]["id"], base["placement"]["id"], version,
                flight_start="2026-06-10", flight_end="2026-06-15", gross_cents=1_000_000,
            ),
            base["mia_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_ELIGIBLE.value)

        plan = validate_success(api.get_media_plan(base["plan_display"]["id"], base["mia_headers"]))
        assert plan["uncommitted_cents"] == 10_000_000

        occupying = validate_success(
            api.get_insertion_order(base["occupying"]["id"], base["mia_headers"])
        )
        assert occupying["status"] == "RESERVED"


def test_an_order_exactly_exhausting_the_budget_is_accepted_and_the_next_cent_is_not(api):
    """PRD §3.7: "Finally, the money must be there: the order's `gross_cents` must not exceed
    the plan's `uncommitted_cents` as it stands *before* the commitment. Exactly equal to the
    uncommitted balance is accepted; strictly greater is rejected with
    `ERR_MEDIA_BUDGET_EXCEEDED`."

    Design: Corner/calculations/media_budget_exactly_equal_to_uncommitted_is_accepted
    """
    base = setup_base()
    first_slot = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
    second_slot = register_placement(publisher_name="TubeCo", channel="VIDEO", min_dark_days=0)
    plan = setup_media_plan(base, approved_budget_cents=10_000_000, allowed_channels=["VIDEO"])

    order = reserve_insertion_order(
        base, plan["id"], first_slot["id"], flight_start="2026-06-05",
        flight_end="2026-06-20", gross_cents=10_000_000,
    )
    assert order["gross_cents"] == 10_000_000

    drained = validate_success(api.get_media_plan(plan["id"], base["mia_headers"]))
    assert drained["uncommitted_cents"] == 0

    resp = api.create_insertion_order(
        create_insertion_order_payload(
            plan["id"], second_slot["id"], drained["version"],
            flight_start="2026-06-05", flight_end="2026-06-20", gross_cents=1,
        ),
        base["mia_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_MEDIA_BUDGET_EXCEEDED.value)
    assert resp.status_code == 422

    after = validate_success(api.get_media_plan(plan["id"], base["mia_headers"]))
    assert after["uncommitted_cents"] == 0


def test_a_cancelled_order_cannot_be_sent_to_the_publisher(api):
    """PRD §3.7: "Cancellation is the compensating action of creation and is legal from
    `RESERVED` and from `PLACED`. It moves the order to the terminal `CANCELLED` state and adds
    the order's `gross_cents` straight back into the plan's `uncommitted_cents`, incrementing
    both the order's and the plan's `version`."
    PRD §2.8: "The target entity is in a state from which the requested transition is legal —
    otherwise `ERR_INVALID_STATE` (HTTP 409). This applies to every action endpoint: approving
    an already-`APPROVED` deliverable, issuing an already-`ISSUED` invoice, placing a
    `CANCELLED` insertion order, paying an invoice that is still `DRAFT`, and voiding an invoice
    against which cash has already been received all land here."

    Design: Corner/state_machines/cancelled_insertion_order_cannot_be_placed
    """
    base = setup_base()
    placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
    plan = setup_media_plan(base, approve=True, approved_budget_cents=10_000_000,
                            allowed_channels=["VIDEO"])
    order = reserve_insertion_order(
        base, plan["id"], placement["id"], flight_start="2026-06-05",
        flight_end="2026-06-20", gross_cents=1_000_000,
    )
    validate_success(api.cancel_insertion_order(order["id"], base["mia_headers"]))

    resp = api.place_insertion_order(order["id"], base["mia_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409

    after = validate_success(api.get_insertion_order(order["id"], base["mia_headers"]))
    assert after["status"] == "CANCELLED"

    plan_after = validate_success(api.get_media_plan(plan["id"], base["mia_headers"]))
    assert plan_after["uncommitted_cents"] == 10_000_000, "no budget is re-committed"


def test_media_plan_version_advances_by_one_per_mutation(api):
    """PRD §2.4: "`version` is an integer that starts at 1 when the resource is created. Every
    mutation of a resource — whether triggered directly by the caller or indirectly as the
    consequence of some other operation elsewhere in the system — refreshes that resource's
    `updated_at` and increments its `version` by exactly 1."
    PRD §3.7: "An accepted order is created in `RESERVED`, and the plan's `uncommitted_cents` is
    reduced by the order's `gross_cents`; the plan's `version` moves with it."
    PRD §3.7: "It moves the order to the terminal `CANCELLED` state and adds the order's
    `gross_cents` straight back into the plan's `uncommitted_cents`, incrementing both the
    order's and the plan's `version`."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation_of_a_media_plan
    """
    base = setup_base()
    placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)

    plan = setup_media_plan(base, approved_budget_cents=10_000_000, allowed_channels=["VIDEO"])
    assert plan["version"] == 1

    approved = validate_success(api.approve_media_plan(plan["id"], base["reviewer_headers"]))
    assert approved["version"] == 2

    order = reserve_insertion_order(
        base, plan["id"], placement["id"], expected_version=2, flight_start="2026-06-05",
        flight_end="2026-06-20", gross_cents=1_000_000,
    )
    assert media_plan_version(plan["id"], base["mia_headers"]) == 3

    place_insertion_order(base, order["id"])
    validate_success(api.cancel_insertion_order(order["id"], base["mia_headers"]))

    final = validate_success(api.get_media_plan(plan["id"], base["mia_headers"]))
    assert final["version"] == 4, "approve, reserve and cancel move the plan; place does not"
    assert final["uncommitted_cents"] == 10_000_000


def test_placing_an_unknown_insertion_order_is_not_found(api, media_buyer_headers):
    """PRD §2.8: "Every identifier embedded in the URL path resolves to a live resource, checked
    left to right — otherwise the matching not-found error for the entity that failed
    (`ERR_CLIENT_NOT_FOUND`, `ERR_RETAINER_NOT_FOUND`, `ERR_SOW_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_TIME_ENTRY_NOT_FOUND`,
    `ERR_VENDOR_COST_NOT_FOUND`, `ERR_MEDIA_PLAN_NOT_FOUND`, `ERR_INSERTION_ORDER_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`), all
    HTTP 404."

    Design: Corner/errors/place_insertion_order_with_unknown_id_returns_insertion_order_not_found
    """
    from test_helpers import set_clock

    set_clock("2026-06-01T00:00:00Z")

    resp = api.place_insertion_order(NON_EXISTENT_UUID, media_buyer_headers)
    validate_error(resp, ApiErrorId.ERR_INSERTION_ORDER_NOT_FOUND.value)
    assert resp.status_code == 404


def test_unknown_placement_is_reported_before_the_budget_ceiling(api):
    """PRD §2.8: "Every foreign key carried in the request body resolves, checked in the order
    the fields are listed for that endpoint — otherwise the matching not-found error, including
    `ERR_MEDIA_PLACEMENT_NOT_FOUND` when an insertion order names a publisher slot that does not
    exist."
    PRD §2.8: "Capacity and budget ceilings, evaluated last of all: the daily minute cap and the
    labor cap on time-entry creation (`ERR_DAILY_MINUTES_EXCEEDED`, `ERR_SOW_LABOR_CAP_EXCEEDED`),
    the media budget ceiling on insertion-order creation (`ERR_MEDIA_BUDGET_EXCEEDED`), and the
    overpayment check on invoice payment (`ERR_PAYMENT_EXCEEDS_BALANCE`), all HTTP 422."

    Design: Corner/errors/create_insertion_order_with_unknown_placement_returns_media_placement_not_found
    """
    base = setup_base()
    plan = setup_media_plan(base, approved_budget_cents=10_000_000, allowed_channels=["VIDEO"])

    resp = api.create_insertion_order(
        create_insertion_order_payload(
            plan["id"], NON_EXISTENT_UUID, plan["version"],
            flight_start="2026-06-05", flight_end="2026-06-20", gross_cents=99_999_999_999,
        ),
        base["mia_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_MEDIA_PLACEMENT_NOT_FOUND.value)
    assert resp.status_code == 404
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_MEDIA_BUDGET_EXCEEDED.value

    after = validate_success(api.get_media_plan(plan["id"], base["mia_headers"]))
    assert after["uncommitted_cents"] == 10_000_000


def test_performance_report_derives_effective_cpm_from_delivered_orders(api):
    """PRD §3.9: "Only insertion orders belonging to a media plan of the campaign and sitting in
    `DELIVERED` contribute media figures: `delivered_impressions` is the sum of their
    `delivered_impressions` and `delivered_spend_cents` the sum of their `delivered_spend_cents`.
    `effective_cpm_cents` — the cost per thousand impressions actually achieved — is
    `delivered_spend_cents` multiplied by 1000 and divided by `delivered_impressions`, rounded
    half up to a whole cent; when no impressions were delivered it reports 0 rather than failing."
    PRD §3.7: "After the flight the buyer records the publisher's post-flight figures, moving
    `PLACED → DELIVERED` and setting `delivered_impressions` and `delivered_spend_cents` to the
    supplied values; until that point both read 0."

    Design: Corner/calculations/performance_report_effective_cpm_from_delivered_orders
    """
    base = setup_base()
    placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
    plan = setup_media_plan(base, approve=True, approved_budget_cents=20_000_000,
                            allowed_channels=["VIDEO"])
    order = reserve_insertion_order(
        base, plan["id"], placement["id"], flight_start="2026-06-05",
        flight_end="2026-06-20", gross_cents=4_000_000,
    )
    place_insertion_order(base, order["id"])

    delivered = deliver_insertion_order(base, order["id"], 2_000_000, 3_600_000)
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivered_impressions"] == 2_000_000

    report = validate_success(
        api.get_campaign_performance_report(base["campaign_id"], base["mia_headers"])
    )
    assert report["delivered_impressions"] == 2_000_000
    assert report["delivered_spend_cents"] == 3_600_000
    assert report["effective_cpm_cents"] == 1_800
    assert report["direct_cost_cents"] == 0
    assert report["billed_revenue_cents"] == 0


def test_performance_report_reports_zero_cpm_when_nothing_was_delivered(api):
    """PRD §3.9: "`effective_cpm_cents` — the cost per thousand impressions actually achieved —
    is `delivered_spend_cents` multiplied by 1000 and divided by `delivered_impressions`,
    rounded half up to a whole cent; when no impressions were delivered it reports 0 rather than
    failing."
    PRD §3.9: "On the cost side, `direct_cost_cents` is the sum of `internal_cost_cents` across
    the campaign's time entries whose status is `APPROVED` or `BILLED`, plus the sum of
    `actual_amount_cents` across the campaign's vendor costs whose status is `APPROVED` or
    `BILLED`; entries and costs still `SUBMITTED` are excluded, but non-billable time entries
    **do** contribute their internal cost — unbillable work is still work the agency paid for.
    `agency_gross_profit_cents` is `billed_revenue_cents` less `direct_cost_cents`, and
    `gross_margin_pct` is that profit divided by `billed_revenue_cents`, multiplied by 100 and
    rounded half up to one decimal place — or 0.0 when no revenue has been billed."

    Design: Corner/calculations/performance_report_with_zero_delivered_impressions
    """
    base = setup_base()
    log_and_approve_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")

    report = validate_success(
        api.get_campaign_performance_report(base["campaign_id"], base["am_headers"])
    )
    assert report["delivered_impressions"] == 0
    assert report["delivered_spend_cents"] == 0
    assert report["effective_cpm_cents"] == 0
    assert report["billed_revenue_cents"] == 0
    assert report["direct_cost_cents"] == 6_000, "60 minutes at an internal cost of 6000 c/h"
    assert report["agency_gross_profit_cents"] == -6_000
    assert report["gross_margin_pct"] == 0.0
