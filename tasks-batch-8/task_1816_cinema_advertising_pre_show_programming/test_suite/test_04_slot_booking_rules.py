"""Slot reservation: state/campaign gates, constraint tier (exclusivity,
interval overlap, pool capacity), temporal tier, and the fiscal tier."""
from test_helpers import (
    ApiErrorId, constants, create_advertiser, create_approved_campaign,
    create_campaign_payload, create_showtime_payload, create_showtime_with_reel,
    make_network_ops_headers, make_sales_manager_headers, reserve_slot,
    setup_showtime_with_reel, setup_theater_screen_feature, validate_error,
    validate_success,
)
from test_helpers.factories import create_slot_payload
from test_helpers.fixtures import SM_CREATOR, get_reel_version


def _bookable_reel(starts_at=constants.OPENING_EVENING_START):
    """Master data + showtime/reel only. Returns (theater, screen, feature, showtime, reel)."""
    return setup_showtime_with_reel(starts_at=starts_at)


class TestCrossEntityCampaignGate:
    def test_slot_create_requires_campaign_approved_rejects_submitted(self, api):
        """PRD §3.3: "only then is the body-referenced campaign examined, with
        any `campaign_status` other than `APPROVED` rejected as
        `ERR_CAMPAIGN_NOT_BOOKABLE`."

        Design: Difficulty/cross_entity_state_dependency/slot_create_requires_campaign_approved
        """
        _, _, _, _, reel = _bookable_reel()
        advertiser = create_advertiser()
        campaign_resp = api.create_campaign(
            create_campaign_payload(advertiser["id"]),
            make_sales_manager_headers(SM_CREATOR))
        campaign = validate_success(campaign_resp, expected_status=201)
        api.submit_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        resp = api.create_slot(reel["id"], create_slot_payload(campaign["id"], reel["version"]),
                               make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_BOOKABLE)

    def test_slot_create_succeeds_after_approval(self, api):
        """PRD §3.3: "A reservation that passes every tier lands with
        `slot_status` `RESERVED`"

        Design: Difficulty/cross_entity_state_dependency/slot_create_requires_campaign_approved
        """
        _, _, _, _, reel = _bookable_reel()
        campaign = create_approved_campaign()
        resp = api.create_slot(reel["id"], create_slot_payload(campaign["id"], reel["version"]),
                               make_sales_manager_headers(SM_CREATOR))
        slot = validate_success(resp, expected_status=201)
        assert slot["slot_status"] == "RESERVED"
        assert slot["campaign_id"] == campaign["id"]


class TestPriorityPairs:
    def test_state_beats_fiscal_on_slot_create(self, api):
        """PRD §2.6: "7. **State preconditions** — the guards of §3, failing
        with the state-tier errors listed in §5."
        PRD §2.6: "11. **Fiscal tier, always last** — the campaign budget cap on
        slot creation, failing as `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_slot_create
        """
        _, _, _, _, reel = _bookable_reel()
        # budget 100 < estimated cost 330, and the campaign is CANCELED.
        campaign = create_approved_campaign(budget_cents=100)
        resp = api.cancel_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        validate_success(resp)
        resp = api.create_slot(reel["id"], create_slot_payload(campaign["id"], reel["version"]),
                               make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_BOOKABLE)

    def test_state_beats_fiscal_also_after_state_cleared(self, api):
        """PRD §2.6: "11. **Fiscal tier, always last** — the campaign budget cap
        on slot creation, failing as `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_slot_create
        """
        _, _, _, _, reel = _bookable_reel()
        campaign = create_approved_campaign(budget_cents=100)
        resp = api.create_slot(reel["id"], create_slot_payload(campaign["id"], reel["version"]),
                               make_sales_manager_headers(SM_CREATOR))
        # With the campaign APPROVED, the state tier passes and the fiscal tier fires.
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)

    def test_safety_beats_constraint_on_slot_create(self, api):
        """PRD §2.6: "8. **Rating-based placement** — the advertiser-category
        versus content-rating rule of §3.3, failing as
        `ERR_RATING_PLACEMENT_VIOLATION`."
        PRD §2.6: "9. **Constraint tier** — for slot creation, evaluated in this
        order: category exclusivity, then interval overlap, then pool capacity."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_slot_create
        """
        # G-rated feature so ALCOHOL placement fails the safety tier.
        _, _, _, _, reel = _bookable_reel()
        c1 = create_approved_campaign()
        reserve_slot(reel["id"], c1["id"], start_offset_seconds=0, duration_seconds=60)
        alcohol_advertiser = create_advertiser(name="BrewCo", category="ALCOHOL")
        c2 = create_approved_campaign(advertiser_id=alcohol_advertiser["id"], name="C2")
        # But the feature behind the reel is PG13 in the default chain; rebuild
        # with a G-rated feature so the safety tier actually fires.
        # (See the paired test below for the PG13-allowed case.)
        resp = api.create_slot(reel["id"], create_slot_payload(
            c2["id"], get_reel_version(reel["id"], make_sales_manager_headers(SM_CREATOR)),
            start_offset_seconds=30, duration_seconds=30),
            make_sales_manager_headers(SM_CREATOR))
        # On a PG13 feature ALCOHOL is forbidden, so the safety tier fires
        # before the interval-overlap tier even though [30,60) intersects [0,60).
        validate_error(resp, ApiErrorId.ERR_RATING_PLACEMENT_VIOLATION)

    def test_safety_beats_constraint_on_g_rated_feature(self, api):
        """PRD §3.3: "An `ALCOHOL` advertiser's slot is permitted only on
        showtimes whose feature's `content_rating` is `R` or `NC17`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_slot_create
        """
        _, _, _, _, reel = setup_showtime_with_reel(
            feature_overrides={"title": "Toon Fest", "content_rating": "G", "runtime_minutes": 90})
        c1 = create_approved_campaign()
        reserve_slot(reel["id"], c1["id"], start_offset_seconds=0, duration_seconds=60)
        alcohol_advertiser = create_advertiser(name="BrewCo", category="ALCOHOL")
        c2 = create_approved_campaign(advertiser_id=alcohol_advertiser["id"], name="C2")
        resp = api.create_slot(reel["id"], create_slot_payload(
            c2["id"], get_reel_version(reel["id"], make_sales_manager_headers(SM_CREATOR)),
            start_offset_seconds=30, duration_seconds=30),
            make_sales_manager_headers(SM_CREATOR))
        # [30,60) intersects [0,60) but the safety tier speaks first.
        validate_error(resp, ApiErrorId.ERR_RATING_PLACEMENT_VIOLATION)


class TestPoolCapacityBoundary:
    def test_pool_capacity_exact_fill_allowed(self, api):
        """PRD §3.3: "if the resulting total strictly exceeds the corresponding
        pool — `national_pool_seconds` of 720 or `local_pool_seconds` of 480 —
        the reservation is rejected with `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422);
        a total exactly equal to the pool's capacity is allowed."

        Design: Difficulty/boundary_precision_check/pool_capacity_exact_fill_allowed
        """
        _, _, _, _, reel = _bookable_reel()
        c1 = create_approved_campaign(name="C1", budget_cents=900000)
        c2 = create_approved_campaign(name="C2", category="QSR", budget_cents=900000,
                                      advertiser_id=create_advertiser(name="BurgerCo", category="QSR")["id"])
        reserve_slot(reel["id"], c1["id"], start_offset_seconds=0, duration_seconds=700)
        slot2 = reserve_slot(reel["id"], c2["id"], start_offset_seconds=700, duration_seconds=20)
        assert slot2["slot_status"] == "RESERVED"
        resp = api.get_reel(reel["id"], make_sales_manager_headers(SM_CREATOR))
        reel_after = validate_success(resp)
        assert reel_after["national_used_seconds"] == 720

    def test_pool_capacity_one_second_over_rejected(self, api):
        """PRD §3.3: "if the resulting total strictly exceeds the corresponding
        pool — `national_pool_seconds` of 720 or `local_pool_seconds` of 480 —
        the reservation is rejected with `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422);
        a total exactly equal to the pool's capacity is allowed."

        Design: Difficulty/boundary_precision_check/pool_capacity_exact_fill_allowed
        """
        _, _, _, _, reel = _bookable_reel()
        c1 = create_approved_campaign(name="C1", budget_cents=900000)
        c2 = create_approved_campaign(name="C2",
                                      advertiser_id=create_advertiser(name="BurgerCo", category="QSR")["id"],
                                      budget_cents=900000)
        c3 = create_approved_campaign(name="C3",
                                      advertiser_id=create_advertiser(name="ShopCo", category="RETAIL")["id"],
                                      budget_cents=900000)
        reserve_slot(reel["id"], c1["id"], start_offset_seconds=0, duration_seconds=700)
        reserve_slot(reel["id"], c2["id"], start_offset_seconds=700, duration_seconds=20)
        version_before = get_reel_version(reel["id"], make_sales_manager_headers(SM_CREATOR))
        # A 1-second slot at offset 720 would push national usage to 721 > 720.
        # It lands in the local pool only if the advertiser is LOCAL; ShopCo is
        # NATIONAL, so the national pool check rejects it.
        resp = api.create_slot(reel["id"], create_slot_payload(c3["id"], version_before,
                                                               start_offset_seconds=720,
                                                               duration_seconds=1),
                               make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_POOL_CAPACITY_EXCEEDED)
        # The rejected reservation leaves the reel version unchanged.
        assert get_reel_version(reel["id"], make_sales_manager_headers(SM_CREATOR)) == version_before


class TestCompensatingInvariants:
    def test_reel_pool_seconds_conserved_across_add_cancel(self, api):
        """PRD §3.3: "Cancellation moves the slot `RESERVED → CANCELED`,
        releases its `duration_seconds` back to whichever pool it drew from,
        subtracts its `estimated_cost_cents` from the campaign's
        `reserved_estimated_cents`, and increments the reel's `version` by one."

        Design: Difficulty/compensating_invariant/reel_pool_seconds_conserved_across_add_cancel
        """
        _, _, _, _, reel = _bookable_reel()
        campaign = create_approved_campaign()
        slot = reserve_slot(reel["id"], campaign["id"], duration_seconds=60)
        resp = api.get_reel(reel["id"], make_network_ops_headers())
        assert validate_success(resp)["national_used_seconds"] == 60
        resp = api.cancel_slot(slot["id"], make_sales_manager_headers(SM_CREATOR))
        validate_success(resp)
        resp = api.get_reel(reel["id"], make_network_ops_headers())
        reel_after = validate_success(resp)
        assert reel_after["national_used_seconds"] == 0
        # Conservation: used + free == pool throughout.
        assert reel_after["national_used_seconds"] <= reel_after["national_pool_seconds"]

    def test_reel_pool_invariant_holds_after_add(self, api):
        """PRD §3.1: "split into a `national_pool_seconds` of 720 reservable by
        `NATIONAL` advertisers and a `local_pool_seconds` of 480 reservable by
        `LOCAL` ones, with `national_used_seconds` and `local_used_seconds` both
        starting at zero"

        Design: Difficulty/compensating_invariant/reel_pool_seconds_conserved_across_add_cancel
        """
        _, _, _, _, reel = _bookable_reel()
        campaign = create_approved_campaign()
        reserve_slot(reel["id"], campaign["id"], duration_seconds=60)
        resp = api.get_reel(reel["id"], make_network_ops_headers())
        reel_after = validate_success(resp)
        assert reel_after["national_used_seconds"] == 60
        assert reel_after["national_pool_seconds"] - reel_after["national_used_seconds"] == 660

    def test_campaign_reserved_cents_conserved_across_add_cancel(self, api):
        """PRD §3.3: "At reservation time the slot snapshots its
        `estimated_cost_cents` — the showtime's `forecast_attendance` multiplied
        by the campaign's `cpm_cents`, divided by 1000, and rounded half-up to a
        whole cent"
        PRD §3.3: "Cancellation moves the slot `RESERVED → CANCELED`, releases
        its `duration_seconds` back to whichever pool it drew from, subtracts
        its `estimated_cost_cents` from the campaign's `reserved_estimated_cents`"

        Design: Difficulty/compensating_invariant/campaign_reserved_cents_conserved_across_add_cancel
        """
        _, _, _, _, reel = _bookable_reel()
        campaign = create_approved_campaign()
        slot = reserve_slot(reel["id"], campaign["id"], duration_seconds=60)
        # round_half_up(132 x 2500 / 1000) == 330
        assert slot["estimated_cost_cents"] == 330
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["reserved_estimated_cents"] == 330
        api.cancel_slot(slot["id"], make_sales_manager_headers(SM_CREATOR))
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        campaign_after = validate_success(resp)
        assert campaign_after["reserved_estimated_cents"] == 0
        assert campaign_after["budget_cents"] == 500000

    def test_campaign_reserved_cents_snapshot_value(self, api):
        """PRD §3.2: "`reserved_estimated_cents` is the sum of
        `estimated_cost_cents` over the campaign's slots currently in `RESERVED`
        or `CONFIRMED`: it grows as slots are reserved"

        Design: Difficulty/compensating_invariant/campaign_reserved_cents_conserved_across_add_cancel
        """
        _, _, _, _, reel = _bookable_reel()
        campaign = create_approved_campaign()
        reserve_slot(reel["id"], campaign["id"], duration_seconds=60)
        reserve_slot(reel["id"], campaign["id"], start_offset_seconds=60, duration_seconds=60)
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["reserved_estimated_cents"] == 660


class TestTemporalTier:
    def test_slot_outside_flight_window_rejected(self, api):
        """PRD §3.3: "the calendar date of the slot's showtime must fall within
        the campaign's flight window, from `flight_start_date` through
        `flight_end_date` inclusive, or the reservation is rejected with
        `ERR_OUTSIDE_FLIGHT_WINDOW` (HTTP 422)."

        Design: Corner/errors/slot_outside_flight_window_rejected
        """
        _, _, _, _, reel = _bookable_reel(starts_at=constants.STANDARD_EVENING_START)
        campaign = create_approved_campaign()  # flight 2026-08-10..2026-08-20
        resp = api.create_slot(reel["id"], create_slot_payload(campaign["id"], reel["version"]),
                               make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_FLIGHT_WINDOW)


class TestFiscalTier:
    def test_slot_over_budget_rejected(self, api):
        """PRD §3.3: "if adding that estimate to the campaign's current
        `reserved_estimated_cents` would exceed the campaign's `budget_cents`,
        the reservation fails with `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/slot_over_budget_rejected
        """
        _, _, _, _, reel = _bookable_reel()
        campaign = create_approved_campaign(budget_cents=300)
        resp = api.create_slot(reel["id"], create_slot_payload(campaign["id"], reel["version"]),
                               make_sales_manager_headers(SM_CREATOR))
        # Estimated cost is 330 > budget 300.
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


class TestConstraintTier:
    def test_category_exclusivity_conflict_rejected(self, api):
        """PRD §3.3: "no other non-`CANCELED` slot anywhere in the same reel may
        belong to a campaign whose advertiser shares the new slot's `category`,
        or the reservation fails with `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`."

        Design: Corner/errors/category_exclusivity_conflict_rejected
        """
        _, _, _, _, reel = _bookable_reel()
        c1 = create_approved_campaign(name="C1")
        reserve_slot(reel["id"], c1["id"], start_offset_seconds=0, duration_seconds=60)
        other_auto = create_advertiser(name="TruckCo", category="AUTOMOTIVE")
        c2 = create_approved_campaign(advertiser_id=other_auto["id"], name="C2")
        resp = api.create_slot(reel["id"], create_slot_payload(
            c2["id"], get_reel_version(reel["id"], make_sales_manager_headers(SM_CREATOR)),
            start_offset_seconds=60, duration_seconds=30),
            make_sales_manager_headers(SM_CREATOR))
        # [60,90) does not overlap [0,60); the exclusivity rule alone rejects it.
        validate_error(resp, ApiErrorId.ERR_CATEGORY_EXCLUSIVITY_CONFLICT)


class TestSlotHalfOpenOverlap:
    def test_slot_touching_endpoint_allowed(self, api):
        """PRD §3.3: "the new slot occupies the half-open interval from
        `start_offset_seconds` up to but not including `start_offset_seconds`
        plus `duration_seconds`, and if that interval intersects any other
        non-`CANCELED` slot's interval in the reel the reservation fails with
        `ERR_SLOT_INTERVAL_OVERLAP`; two slots that merely touch endpoints do
        not conflict."

        Design: Difficulty/resource_temporal_overlap/slot_halfopen_overlap_in_reel
        """
        _, _, _, _, reel = _bookable_reel()
        c1 = create_approved_campaign(name="C1")
        c2 = create_approved_campaign(name="C2",
                                      advertiser_id=create_advertiser(name="BurgerCo", category="QSR")["id"])
        reserve_slot(reel["id"], c1["id"], start_offset_seconds=0, duration_seconds=60)
        slot_b = reserve_slot(reel["id"], c2["id"], start_offset_seconds=60, duration_seconds=30)
        assert slot_b["slot_status"] == "RESERVED"

    def test_slot_one_second_overlap_rejected(self, api):
        """PRD §3.3: "the new slot occupies the half-open interval from
        `start_offset_seconds` up to but not including `start_offset_seconds`
        plus `duration_seconds`, and if that interval intersects any other
        non-`CANCELED` slot's interval in the reel the reservation fails with
        `ERR_SLOT_INTERVAL_OVERLAP`; two slots that merely touch endpoints do
        not conflict."

        Design: Difficulty/resource_temporal_overlap/slot_halfopen_overlap_in_reel
        """
        _, _, _, _, reel = _bookable_reel()
        c1 = create_approved_campaign(name="C1")
        c2 = create_approved_campaign(name="C2",
                                      advertiser_id=create_advertiser(name="BurgerCo", category="QSR")["id"])
        c3 = create_approved_campaign(name="C3",
                                      advertiser_id=create_advertiser(name="ShopCo", category="RETAIL")["id"])
        reserve_slot(reel["id"], c1["id"], start_offset_seconds=0, duration_seconds=60)
        reserve_slot(reel["id"], c2["id"], start_offset_seconds=60, duration_seconds=30)
        resp = api.create_slot(reel["id"], create_slot_payload(
            c3["id"], get_reel_version(reel["id"], make_sales_manager_headers(SM_CREATOR)),
            start_offset_seconds=89, duration_seconds=15),
            make_sales_manager_headers(SM_CREATOR))
        # [89,104) intersects [60,90) by one second.
        validate_error(resp, ApiErrorId.ERR_SLOT_INTERVAL_OVERLAP)


class TestShowtimeBufferedOverlap:
    def test_showtime_exact_turnaround_gap_allowed(self, api):
        """PRD §3.1: "A gap of exactly thirty minutes between one showtime's end
        and the other's start is permitted."

        Design: Difficulty/resource_temporal_overlap/showtime_buffered_overlap_on_screen
        """
        _, screen, feature = setup_theater_screen_feature()
        first, _ = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-14T19:00:00Z")
        # 120-minute runtime: occupied until 21:00, buffered to 21:30.
        resp = api.create_showtime(screen["id"], create_showtime_payload(
            feature["id"], starts_at="2026-08-14T21:30:00Z"), make_network_ops_headers())
        second = validate_success(resp, expected_status=201)
        assert second["id"] != first["id"]

    def test_showtime_29_minute_gap_rejected(self, api):
        """PRD §3.1: "A new showtime conflicts with an existing one on the same
        screen when the new start falls before the existing showtime's end — the
        existing start plus its feature's `runtime_minutes` — plus a
        thirty-minute turnaround buffer, and at the same time the existing
        showtime's start falls before the new showtime's end plus the same
        thirty-minute buffer. A violation is rejected with
        `ERR_SHOWTIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/showtime_buffered_overlap_on_screen
        """
        _, screen, feature = setup_theater_screen_feature()
        create_showtime_with_reel(screen["id"], feature["id"], "2026-08-14T19:00:00Z")
        resp = api.create_showtime(screen["id"], create_showtime_payload(
            feature["id"], starts_at="2026-08-14T21:29:00Z"), make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_SHOWTIME_OVERLAP)
