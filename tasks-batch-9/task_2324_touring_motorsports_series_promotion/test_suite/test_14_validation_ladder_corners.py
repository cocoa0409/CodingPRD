"""Corner cases of the validation ladder: precedence, inclusive bounds and cross-entity floors.

Each test builds the whole state it needs, because the server is relaunched
against an empty database before every test. All time-dependent behaviour is
driven from the logical clock rather than from wall-clock time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    factories as F,
    fixtures as helpers,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Fixed instants and figures the scenarios below are anchored on
# ---------------------------------------------------------------------------

SHOW_START_UTC = "2026-11-14T23:00:00Z"
STAGING_OPENS_UTC = "2026-11-14T15:00:00Z"
STAGING_CLOSES_UTC = "2026-11-14T21:00:00Z"
JUST_BEFORE_STAGING_OPENS_UTC = "2026-11-14T14:59:59Z"
JUST_AFTER_STAGING_CLOSES_UTC = "2026-11-14T21:00:01Z"
PROMISED_ARRIVAL_UTC = "2026-11-14T16:00:00Z"


def _instant(value: str) -> datetime:
    """The UTC instant an ISO 8601 timestamp denotes, ignoring formatting detail."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestAuthShapeAndPathLadder:
    """The first four rungs of the ladder, each shown to outrank the ones below it."""

    def test_unauthenticated_outranks_the_unresolvable_path(
        self,
        api: ApiClient,
        proposed_booking: Dict[str, Any],
        anonymous_headers: Dict[str, str],
        promoter_headers: Dict[str, str],
    ) -> None:
        """§2.1: "A request with a missing or empty `X-User-ID` is rejected with `ERR_UNAUTHENTICATED` (401)."

        §2.10: "Where several rules could reject the same request, they are evaluated in a fixed order and the first failure determines the response."

        Design: Corner/validations/corner_validation_auth_then_shape_then_path_resolution_ladder
        """
        response = api.withdraw_venue_booking(
            NON_EXISTENT_UUID,
            payload=F.make_withdraw_payload(),
            headers=anonymous_headers,
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

        untouched = get_success_data(
            api.get_venue_booking(
                proposed_booking["booking_id"], headers=promoter_headers
            )
        )
        assert untouched["state"] == "TERMS_PROPOSED"
        assert untouched["version"] == proposed_booking["booking"]["version"]
        assert untouched["withdraw_reason"] is None

    def test_unauthorized_role_outranks_the_missing_body_field(
        self,
        api: ApiClient,
        proposed_booking: Dict[str, Any],
        ticketing_headers: Dict[str, str],
        promoter_headers: Dict[str, str],
    ) -> None:
        """§2.1: "A request whose `X-User-Role` is not among the roles authorized for the addressed endpoint is rejected with `ERR_UNAUTHORIZED` (403)."

        §2.10: "Where several rules could reject the same request, they are evaluated in a fixed order and the first failure determines the response."

        Design: Corner/validations/corner_validation_auth_then_shape_then_path_resolution_ladder
        """
        response = api.withdraw_venue_booking(
            NON_EXISTENT_UUID, payload={}, headers=ticketing_headers
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

        untouched = get_success_data(
            api.get_venue_booking(
                proposed_booking["booking_id"], headers=promoter_headers
            )
        )
        assert untouched["state"] == "TERMS_PROPOSED"
        assert untouched["version"] == proposed_booking["booking"]["version"]

    def test_missing_body_field_outranks_the_unresolvable_path(
        self,
        api: ApiClient,
        proposed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """§2.10: "`ERR_INVALID_REQUEST` (422) — a required body field is missing, a scalar has the wrong type, a date or datetime is malformed, an enum value falls outside its declared set, a quantity, amount or count falls below its declared minimum, `limit` is outside 1 through 100, or `offset` is negative. Every endpoint with a body or query parameters."

        §3.1: "Withdrawal ends a booking. The promoter supplies a `reason`, which is stored as `withdraw_reason`, and the booking moves to `WITHDRAWN`."

        Design: Corner/validations/corner_validation_auth_then_shape_then_path_resolution_ladder
        """
        response = api.withdraw_venue_booking(
            NON_EXISTENT_UUID, payload={}, headers=promoter_headers
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)

        untouched = get_success_data(
            api.get_venue_booking(
                proposed_booking["booking_id"], headers=promoter_headers
            )
        )
        assert untouched["state"] == "TERMS_PROPOSED"
        assert untouched["version"] == proposed_booking["booking"]["version"]

    def test_well_formed_request_on_an_unknown_id_reports_the_entity_404(
        self,
        api: ApiClient,
        proposed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """§2.6: "When a path contains an identifier, the server resolves it before doing anything else, and when a path contains more than one identifier they are resolved strictly left to right."

        §2.10: "The entity-specific 404 — the `{id}` in the path does not resolve to a row of the addressed entity. Every endpoint with a path parameter."

        Design: Corner/validations/corner_validation_auth_then_shape_then_path_resolution_ladder
        """
        payload = F.make_withdraw_payload()
        response = api.withdraw_venue_booking(
            NON_EXISTENT_UUID, payload=payload, headers=promoter_headers
        )
        validate_error(
            response, ApiErrorId.ERR_VENUE_BOOKING_NOT_FOUND, expected_status=404
        )

        # The very same request against the row that does exist is admissible, so
        # each of the rejections above was about the request, not the operation.
        accepted = api.withdraw_venue_booking(
            proposed_booking["booking_id"], payload=payload, headers=promoter_headers
        )
        withdrawn = validate_success(accepted, expected_status=200)
        assert withdrawn["state"] == "WITHDRAWN"
        assert withdrawn["withdraw_reason"] == payload["reason"]
        assert withdrawn["version"] == proposed_booking["booking"]["version"] + 1


class TestStagingWindowInclusiveBounds:
    """Check-in is admitted at both ends of the staging window and refused one second outside it."""

    def _stop_with_three_light_entries(self, api: ApiClient) -> Dict[str, Any]:
        """A certified stop showing at 23:00Z with three light rigs promised for 16:00Z."""
        state = helpers.stop_with_show_timing(api, show_start_utc=SHOW_START_UTC)
        stop_id = state["stop_id"]
        entries = []
        competitor_id = None
        for number in ("41", "42", "43"):
            created = helpers.create_vehicle_entry(
                api,
                stop_id,
                competitor_id=competitor_id,
                vehicle_number=number,
                vehicle_weight_lbs=7000,
                entry_haul_distance_miles=100,
                scheduled_arrival_utc=PROMISED_ARRIVAL_UTC,
            )
            competitor_id = created["competitor_id"]
            entries.append(created["entry"])
        # The plan is certified after the entries exist, because live entries drive
        # the provisioning floors it has to clear.
        state.update(helpers.certified_safety_plan(api, stop_id))
        state["entries"] = entries
        return state

    def test_check_in_one_second_before_the_window_opens_is_refused(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§3.3: "It may be called by the owning `CompetitorTeam` or by the promoter, carries an optional `arrival_note`, and requires three things of the stop: its `safety_state` must be `SAFETY_CERTIFIED`, its posture must not be `FROZEN`, and the current logical clock must sit inside the staging window, which opens 8 hours before `show_start_utc` and closes 2 hours before `show_start_utc`, with both bounds inclusive."

        §3.3: "A clock outside that window is rejected with `ERR_STAGING_WINDOW_CLOSED`; note that `scheduled_arrival_utc` is only a promise and never gates check-in, it only feeds the readiness penalties."

        Design: Corner/validations/corner_validation_staging_window_is_inclusive_at_both_ends
        """
        state = self._stop_with_three_light_entries(api)
        entry_id = state["entries"][0]["id"]

        helpers.set_clock(api, JUST_BEFORE_STAGING_OPENS_UTC)
        response = api.check_in_vehicle_entry(
            entry_id, payload=F.make_check_in_payload(), headers=promoter_headers
        )
        validate_error(
            response, ApiErrorId.ERR_STAGING_WINDOW_CLOSED, expected_status=409
        )

        entry = helpers.fetch_entry(api, entry_id)
        assert entry["logistics_state"] == "ENTERED"
        assert entry["actual_arrival_utc"] is None
        assert entry["version"] == state["entries"][0]["version"]

    def test_check_in_at_the_inclusive_open_bound_is_admitted(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§3.3: "It may be called by the owning `CompetitorTeam` or by the promoter, carries an optional `arrival_note`, and requires three things of the stop: its `safety_state` must be `SAFETY_CERTIFIED`, its posture must not be `FROZEN`, and the current logical clock must sit inside the staging window, which opens 8 hours before `show_start_utc` and closes 2 hours before `show_start_utc`, with both bounds inclusive."

        §3.3: "On success the entry becomes `STAGED`, `actual_arrival_utc` is stamped from the logical clock, the score is recomputed under `POST_STAGING`, and the entry's `version` increments by one."

        §3.3: "Under the **`POST_STAGING`** variant, which runs from check-in onwards while the entry is `STAGED` and is recomputed after every inspection attempt, the projection is discarded entirely: the schedule penalty is 15 points when the actual `actual_arrival_utc` is later than the promised `scheduled_arrival_utc`, and 0 otherwise."

        Design: Corner/validations/corner_validation_staging_window_is_inclusive_at_both_ends
        """
        state = self._stop_with_three_light_entries(api)
        entry_before = state["entries"][0]

        helpers.set_clock(api, STAGING_OPENS_UTC)
        entry = validate_success(
            api.check_in_vehicle_entry(
                entry_before["id"],
                payload=F.make_check_in_payload(),
                headers=promoter_headers,
            ),
            expected_status=200,
        )

        assert entry["logistics_state"] == "STAGED"
        assert _instant(entry["actual_arrival_utc"]) == _instant(STAGING_OPENS_UTC)
        assert entry["readiness_variant"] == "POST_STAGING"
        # Arrived five hours early against a 16:00Z promise, so no schedule penalty,
        # and a 100-mile haul is short of one 500-mile block.
        assert entry["readiness_score"] == 100
        assert entry["version"] == entry_before["version"] + 1

    def test_check_in_at_the_inclusive_close_bound_is_admitted(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§3.3: "It may be called by the owning `CompetitorTeam` or by the promoter, carries an optional `arrival_note`, and requires three things of the stop: its `safety_state` must be `SAFETY_CERTIFIED`, its posture must not be `FROZEN`, and the current logical clock must sit inside the staging window, which opens 8 hours before `show_start_utc` and closes 2 hours before `show_start_utc`, with both bounds inclusive."

        §3.3: "Under the **`POST_STAGING`** variant, which runs from check-in onwards while the entry is `STAGED` and is recomputed after every inspection attempt, the projection is discarded entirely: the schedule penalty is 15 points when the actual `actual_arrival_utc` is later than the promised `scheduled_arrival_utc`, and 0 otherwise."

        Design: Corner/validations/corner_validation_staging_window_is_inclusive_at_both_ends
        """
        state = self._stop_with_three_light_entries(api)
        entry_before = state["entries"][1]

        helpers.set_clock(api, STAGING_CLOSES_UTC)
        entry = validate_success(
            api.check_in_vehicle_entry(
                entry_before["id"],
                payload=F.make_check_in_payload(),
                headers=promoter_headers,
            ),
            expected_status=200,
        )

        assert entry["logistics_state"] == "STAGED"
        assert _instant(entry["actual_arrival_utc"]) == _instant(STAGING_CLOSES_UTC)
        assert entry["readiness_variant"] == "POST_STAGING"
        # 21:00Z is later than the 16:00Z promise, so the 15-point schedule penalty lands.
        assert entry["readiness_score"] == 85

    def test_check_in_one_second_after_the_window_closes_is_refused(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§3.3: "A clock outside that window is rejected with `ERR_STAGING_WINDOW_CLOSED`; note that `scheduled_arrival_utc` is only a promise and never gates check-in, it only feeds the readiness penalties."

        §3.3: "The choice within the candidate set depends on weight: an entry whose `vehicle_weight_lbs` is at least 9000 pounds is a heavy rig and takes the **highest** free bay index, staging nearest the ramp, while a lighter rig takes the **lowest** free index, staging from the far wall."

        Design: Corner/validations/corner_validation_staging_window_is_inclusive_at_both_ends
        """
        state = self._stop_with_three_light_entries(api)
        entry_before = state["entries"][2]

        helpers.set_clock(api, JUST_AFTER_STAGING_CLOSES_UTC)
        response = api.check_in_vehicle_entry(
            entry_before["id"],
            payload=F.make_check_in_payload(),
            headers=promoter_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_STAGING_WINDOW_CLOSED, expected_status=409
        )

        entry = helpers.fetch_entry(api, entry_before["id"])
        assert entry["logistics_state"] == "ENTERED"
        assert entry["actual_arrival_utc"] is None
        assert entry["readiness_variant"] == "PRE_STAGING"
        assert entry["readiness_score"] == 100
        # The refused entry keeps the third-lowest bay it was given on creation.
        assert entry["staging_bay_index"] == 3
        assert entry["version"] == entry_before["version"]


class TestPitPartyCapacityOverPaidOrders:
    """The stop's pit party running total counts paid orders only, and both caps are inclusive."""

    def _stop_with_paid_bundle_order(self, api: ApiClient) -> Dict[str, Any]:
        """An on-sale stop selling 20 pit party heads, 12 of them already paid for."""
        state = helpers.stop_on_sale(
            api,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            include_second_tier=False,
            pit_party_price_cents=4000,
            pit_party_capacity=20,
        )
        state.update(
            helpers.place_paid_ticket_order(
                api,
                state["stop_id"],
                state["tier_id"],
                qty=12,
                pit_party_addon_qty=12,
            )
        )
        return state

    def test_paid_bundle_order_sets_the_running_pit_party_total(
        self, api: ApiClient
    ) -> None:
        """§3.2: "The stop also tracks `pit_party_sold_count`, the sum of `pit_party_addon_qty` over its orders that reached `PAID`."

        §3.7: "The pit party bundle rate applies when `pit_party_addon_qty` is greater than 0 **and** exactly equal to `qty` — every seat on the order brings a head to the pit party. When it applies, `addon_discount_cents` is `addon_subtotal_cents` multiplied by 15 percent, rounded half up to whole cents; when it does not apply, `addon_discount_cents` is 0."

        §3.7: "Payment stamps `paid_at` from the logical clock, moves `qty` from the tier's `reserved_seat_count` to its `sold_seat_count` while leaving `available_seat_count` unchanged, and adds four amounts and two counts to the stop's roll-ups: `line_subtotal_cents` minus `group_discount_cents` goes to `gross_ticket_revenue_cents`, `addon_subtotal_cents` minus `addon_discount_cents` goes to `addon_revenue_cents`, `facility_fee_cents` goes to `facility_fee_collected_cents`, `qty` goes to `tickets_sold_count`, and `pit_party_addon_qty` goes to `pit_party_sold_count`."

        Design: Corner/validations/corner_validation_pit_party_capacity_aggregates_over_paid_orders_only
        """
        state = self._stop_with_paid_bundle_order(api)
        order = state["order"]

        assert order["status"] == "PAID"
        assert order["line_subtotal_cents"] == 38400
        assert order["group_discount_cents"] == 0
        assert order["addon_subtotal_cents"] == 48000
        assert order["addon_discount_cents"] == 7200
        assert order["facility_fee_cents"] == 4200
        assert order["total_cents"] == 83400

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["pit_party_sold_count"] == 12
        assert stop["addon_revenue_cents"] == 40800
        assert stop["tickets_sold_count"] == 12
        assert stop["gross_ticket_revenue_cents"] == 38400

    def test_running_total_plus_new_heads_over_capacity_is_refused(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """§3.7: "Pit party heads are capped twice: `pit_party_addon_qty` may not exceed `qty`, and the stop's `pit_party_sold_count` plus this order's `pit_party_addon_qty` may not exceed the stop's `pit_party_capacity`; either breach is rejected with `ERR_PIT_PARTY_CAPACITY_EXCEEDED`."

        §3.2: "The stop also tracks `pit_party_sold_count`, the sum of `pit_party_addon_qty` over its orders that reached `PAID`."

        Design: Corner/validations/corner_validation_pit_party_capacity_aggregates_over_paid_orders_only
        """
        state = self._stop_with_paid_bundle_order(api)
        stop_id = state["stop_id"]
        tier_id = state["tier_id"]
        version_before = helpers.fetch_tier_version(api, tier_id)

        # 12 heads already paid for plus 9 more is 21, one over the stop's 20.
        response = api.create_ticket_order(
            F.make_ticket_order_payload(
                stop_id, tier_id, version_before, qty=10, pit_party_addon_qty=9
            ),
            headers=ticketing_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_PIT_PARTY_CAPACITY_EXCEEDED, expected_status=409
        )

        _rows, meta = validate_paginated(
            api.list_ticket_orders(
                params={"tour_stop_id": stop_id}, headers=ticketing_headers
            )
        )
        assert meta["total_count"] == 1

        tier = helpers.fetch_tier(api, tier_id)
        assert tier["version"] == version_before
        assert tier["reserved_seat_count"] == 0
        assert tier["sold_seat_count"] == 12
        assert tier["available_seat_count"] == 488

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["pit_party_sold_count"] == 12

    def test_more_heads_than_seats_on_one_order_is_refused(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """§3.7: "Pit party heads are capped twice: `pit_party_addon_qty` may not exceed `qty`, and the stop's `pit_party_sold_count` plus this order's `pit_party_addon_qty` may not exceed the stop's `pit_party_capacity`; either breach is rejected with `ERR_PIT_PARTY_CAPACITY_EXCEEDED`."

        Design: Corner/validations/corner_validation_pit_party_capacity_aggregates_over_paid_orders_only
        """
        state = self._stop_with_paid_bundle_order(api)
        stop_id = state["stop_id"]
        tier_id = state["tier_id"]
        version_before = helpers.fetch_tier_version(api, tier_id)

        # Four heads on three seats breaks the per-order cap even though 12 + 4
        # would still sit inside the stop's capacity of 20.
        response = api.create_ticket_order(
            F.make_ticket_order_payload(
                stop_id, tier_id, version_before, qty=3, pit_party_addon_qty=4
            ),
            headers=ticketing_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_PIT_PARTY_CAPACITY_EXCEEDED, expected_status=409
        )

        _rows, meta = validate_paginated(
            api.list_ticket_orders(
                params={"tour_stop_id": stop_id}, headers=ticketing_headers
            )
        )
        assert meta["total_count"] == 1

        tier = helpers.fetch_tier(api, tier_id)
        assert tier["version"] == version_before
        assert tier["reserved_seat_count"] == 0
        assert helpers.fetch_stop(api, stop_id)["pit_party_sold_count"] == 12

    def test_heads_landing_exactly_on_capacity_are_admitted_and_stay_unpaid(
        self, api: ApiClient
    ) -> None:
        """§3.7: "Pit party heads are capped twice: `pit_party_addon_qty` may not exceed `qty`, and the stop's `pit_party_sold_count` plus this order's `pit_party_addon_qty` may not exceed the stop's `pit_party_capacity`; either breach is rejected with `ERR_PIT_PARTY_CAPACITY_EXCEEDED`."

        §3.2: "The stop also tracks `pit_party_sold_count`, the sum of `pit_party_addon_qty` over its orders that reached `PAID`."

        Design: Corner/validations/corner_validation_pit_party_capacity_aggregates_over_paid_orders_only
        """
        state = self._stop_with_paid_bundle_order(api)
        stop_id = state["stop_id"]
        tier_id = state["tier_id"]

        pending = helpers.place_ticket_order(
            api, stop_id, tier_id, qty=10, pit_party_addon_qty=8
        )
        order = pending["order"]
        assert order["status"] == "PENDING"
        assert order["line_subtotal_cents"] == 32000
        assert order["addon_subtotal_cents"] == 32000
        # Eight heads on ten seats is not a full bundle, so no add-on discount.
        assert order["addon_discount_cents"] == 0
        assert order["facility_fee_cents"] == 3500
        assert order["total_cents"] == 67500

        # The new heads are only reserved, not sold, so the running total is untouched.
        stop = helpers.fetch_stop(api, stop_id)
        assert stop["pit_party_sold_count"] == 12

        tier = helpers.fetch_tier(api, tier_id)
        assert tier["reserved_seat_count"] == 10
        assert tier["sold_seat_count"] == 12
        assert tier["available_seat_count"] == 478


class TestGroupRateConditionalOnTheFlag:
    """The group threshold only bites when the flag is set, and it is read from the addressed tier."""

    def _stop_with_two_group_profiles(self, api: ApiClient) -> Dict[str, Any]:
        """An on-sale stop with a defaulted GA tier and a CLUB tier carrying its own terms."""
        state = helpers.stop_on_sale(
            api,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            group_min_qty=None,
            group_discount_pct=None,
            include_second_tier=False,
        )
        club = helpers.create_ticket_tier(
            api,
            state["stop_id"],
            tier_code="CLUB",
            price_cents=5000,
            allotment=100,
            group_min_qty=10,
            group_discount_pct=0.2,
        )
        state["club_tier"] = club["tier"]
        state["club_tier_id"] = club["tier_id"]
        return state

    def test_group_order_below_the_tier_minimum_is_refused(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """§3.7: "If `is_group` is true, `qty` must reach the tier's `group_min_qty`, or the order is rejected with `ERR_GROUP_MINIMUM_NOT_MET`."

        §3.6: "Group-sales terms are `group_min_qty`, the minimum seats on one order to qualify for the group rate, which must be at least 1 and defaults to 20, and `group_discount_pct`, the discount applied to the ticket line when the threshold is met, which must lie between 0 and 1 inclusive and defaults to 0.125."

        Design: Corner/validations/corner_validation_group_rate_rule_is_conditional_on_the_is_group_flag
        """
        state = self._stop_with_two_group_profiles(api)
        stop_id = state["stop_id"]
        tier_id = state["tier_id"]

        assert state["tier"]["group_min_qty"] == 20
        version_before = helpers.fetch_tier_version(api, tier_id)

        response = api.create_ticket_order(
            F.make_ticket_order_payload(
                stop_id, tier_id, version_before, qty=19, is_group=True
            ),
            headers=ticketing_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_GROUP_MINIMUM_NOT_MET, expected_status=422
        )

        _rows, meta = validate_paginated(
            api.list_ticket_orders(
                params={"tour_stop_id": stop_id}, headers=ticketing_headers
            )
        )
        assert meta["total_count"] == 0

        tier = helpers.fetch_tier(api, tier_id)
        assert tier["version"] == version_before
        assert tier["reserved_seat_count"] == 0
        assert tier["available_seat_count"] == 500

    def test_same_seat_count_without_the_group_flag_is_admitted_undiscounted(
        self, api: ApiClient
    ) -> None:
        """§3.7: "If `is_group` is true, `qty` must reach the tier's `group_min_qty`, or the order is rejected with `ERR_GROUP_MINIMUM_NOT_MET`."

        §3.7: "The group rate applies when `is_group` is true **and** `qty` is at least the tier's `group_min_qty`. When it applies, `group_discount_cents` is `line_subtotal_cents` multiplied by the tier's `group_discount_pct`, rounded half up to whole cents; when it does not apply, `group_discount_cents` is 0."

        Design: Corner/validations/corner_validation_group_rate_rule_is_conditional_on_the_is_group_flag
        """
        state = self._stop_with_two_group_profiles(api)

        placed = helpers.place_ticket_order(
            api, state["stop_id"], state["tier_id"], qty=19
        )
        order = placed["order"]
        assert order["status"] == "PENDING"
        assert order["is_group"] is False
        assert order["line_subtotal_cents"] == 60800
        assert order["group_discount_cents"] == 0
        assert order["facility_fee_cents"] == 6650
        assert order["total_cents"] == 67450

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["reserved_seat_count"] == 19

    def test_group_order_at_the_inclusive_minimum_earns_the_tier_discount(
        self, api: ApiClient
    ) -> None:
        """§3.7: "The group rate applies when `is_group` is true **and** `qty` is at least the tier's `group_min_qty`. When it applies, `group_discount_cents` is `line_subtotal_cents` multiplied by the tier's `group_discount_pct`, rounded half up to whole cents; when it does not apply, `group_discount_cents` is 0."

        §3.7: "`facility_fee_cents` is the `per_ticket_facility_fee_cents` from the stop's booking — the terms in force when the booking was confirmed — multiplied by `qty`. The facility fee is never discounted."

        Design: Corner/validations/corner_validation_group_rate_rule_is_conditional_on_the_is_group_flag
        """
        state = self._stop_with_two_group_profiles(api)

        placed = helpers.place_ticket_order(
            api, state["stop_id"], state["tier_id"], qty=20, is_group=True
        )
        order = placed["order"]
        assert order["is_group"] is True
        assert order["line_subtotal_cents"] == 64000
        # 64000 at the defaulted 0.125 rate.
        assert order["group_discount_cents"] == 8000
        assert order["facility_fee_cents"] == 7000
        assert order["total_cents"] == 63000

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["reserved_seat_count"] == 20

    def test_group_threshold_and_rate_come_from_the_addressed_tier(
        self, api: ApiClient
    ) -> None:
        """§3.7: "If `is_group` is true, `qty` must reach the tier's `group_min_qty`, or the order is rejected with `ERR_GROUP_MINIMUM_NOT_MET`."

        §3.7: "The group rate applies when `is_group` is true **and** `qty` is at least the tier's `group_min_qty`. When it applies, `group_discount_cents` is `line_subtotal_cents` multiplied by the tier's `group_discount_pct`, rounded half up to whole cents; when it does not apply, `group_discount_cents` is 0."

        Design: Corner/validations/corner_validation_group_rate_rule_is_conditional_on_the_is_group_flag
        """
        state = self._stop_with_two_group_profiles(api)
        assert state["club_tier"]["group_min_qty"] == 10

        # Ten seats fall well short of the GA tier's threshold but reach the CLUB
        # tier's own, so the same seat count is a group order here.
        placed = helpers.place_ticket_order(
            api, state["stop_id"], state["club_tier_id"], qty=10, is_group=True
        )
        order = placed["order"]
        assert order["is_group"] is True
        assert order["line_subtotal_cents"] == 50000
        assert order["group_discount_cents"] == 10000
        assert order["facility_fee_cents"] == 3500
        assert order["total_cents"] == 43500

        club = helpers.fetch_tier(api, state["club_tier_id"])
        assert club["reserved_seat_count"] == 10
        ga = helpers.fetch_tier(api, state["tier_id"])
        assert ga["reserved_seat_count"] == 0


class TestCatchFenceTracksLiveEntries:
    """The fence floor is driven by rows on another entity and is bounded above by the building."""

    def _stop_with_light_entry_and_draft_plan(
        self, api: ApiClient, catch_fence_height_ft: int
    ) -> Dict[str, Any]:
        """A stop with one light rig and a draft plan provisioned at the given fence height."""
        state = helpers.stop_with_show_timing(api, catch_fence_max_height_ft=10)
        stop_id = state["stop_id"]
        state.update(
            helpers.create_vehicle_entry(
                api, stop_id, vehicle_number="41", vehicle_weight_lbs=7000
            )
        )
        state.update(
            helpers.draft_safety_plan(
                api,
                stop_id,
                barrier_linear_feet=1200,
                catch_fence_height_ft=catch_fence_height_ft,
                medical_als_staff_count=1,
                medical_bls_staff_count=2,
                ambulance_count=1,
                emergency_access_lanes=1,
            )
        )
        return state

    def _enter_heavy_rig(self, api: ApiClient, state: Dict[str, Any]) -> Dict[str, Any]:
        """Add a 9,500 lb rig to the stop, which is what lifts the fence floor to 8 feet."""
        created = helpers.create_vehicle_entry(
            api,
            state["stop_id"],
            competitor_id=state["competitor_id"],
            vehicle_number="88",
            vehicle_weight_lbs=9500,
        )
        return created["entry"]

    def test_certification_fails_when_a_new_entry_lifts_the_fence_floor(
        self,
        api: ApiClient,
        safety_author_headers: Dict[str, str],
        safety_certifier_headers: Dict[str, str],
    ) -> None:
        """§3.5: "`required_catch_fence_height_ft` is 8 feet when a heavy rig is present among the live entries and 6 feet otherwise."

        §3.5: "Entry creation likewise refreshes the stop's requirement figures, since live entries drive ambulances, ALS staffing and barrier footage."

        §3.5: "Certification moves a `SUBMITTED` plan to `CERTIFIED`. It carries an optional `note`, requires that the caller not be the plan's author, and re-checks the identical four provisioning conditions against freshly recomputed floors — a plan that was adequate at submission but was overtaken by a new tier or a new entry in the meantime fails certification with the same shortfall errors listed above."

        §3.5: "The choice within the candidate set depends on weight: an entry whose `vehicle_weight_lbs` is at least 9000 pounds is a heavy rig and takes the **highest** free bay index, staging nearest the ramp, while a lighter rig takes the **lowest** free index, staging from the far wall."

        Design: Corner/validations/corner_validation_catch_fence_requirement_tracks_another_entity_s_rows
        """
        state = self._stop_with_light_entry_and_draft_plan(api, catch_fence_height_ft=6)
        plan_id = state["plan_id"]

        submitted = validate_success(
            api.submit_safety_plan(plan_id, headers=safety_author_headers),
            expected_status=200,
        )
        assert submitted["state"] == "SUBMITTED"
        # One light rig on the floor: the six-foot fence and the 1,200-foot barrier floor.
        assert submitted["required_catch_fence_height_ft"] == 6
        assert submitted["required_barrier_linear_feet"] == 1200
        assert submitted["required_ambulance_count"] == 1

        heavy = self._enter_heavy_rig(api, state)
        assert heavy["staging_bay_index"] == 4

        raised = helpers.fetch_safety_plan(api, plan_id)
        assert raised["required_catch_fence_height_ft"] == 8

        response = api.certify_safety_plan(
            plan_id,
            payload=F.make_certify_payload(),
            headers=safety_certifier_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_CATCH_FENCE_INSUFFICIENT, expected_status=422
        )

        plan = helpers.fetch_safety_plan(api, plan_id)
        assert plan["state"] == "SUBMITTED"
        assert plan["certified_by_user_id"] is None
        assert helpers.fetch_stop(api, state["stop_id"])["safety_state"] == "SAFETY_REVIEW"

    def test_submission_fails_when_the_fence_exceeds_the_buildings_rigging_limit(
        self, api: ApiClient, safety_author_headers: Dict[str, str]
    ) -> None:
        """§3.5: "`catch_fence_height_ft` must be at least `required_catch_fence_height_ft` and at the same time no greater than the booked venue's `catch_fence_max_height_ft`, or `ERR_CATCH_FENCE_INSUFFICIENT`"

        §2.10: "`ERR_CATCH_FENCE_INSUFFICIENT` (422) — fence height below requirement or above the venue's rigging limit. Both submission and certification."

        Design: Corner/validations/corner_validation_catch_fence_requirement_tracks_another_entity_s_rows
        """
        state = self._stop_with_light_entry_and_draft_plan(api, catch_fence_height_ft=11)
        self._enter_heavy_rig(api, state)
        plan_id = state["plan_id"]

        # Eleven feet clears the eight-foot floor but overshoots the building's ten.
        response = api.submit_safety_plan(plan_id, headers=safety_author_headers)
        validate_error(
            response, ApiErrorId.ERR_CATCH_FENCE_INSUFFICIENT, expected_status=422
        )

        plan = helpers.fetch_safety_plan(api, plan_id)
        assert plan["state"] == "DRAFT"
        assert plan["required_catch_fence_height_ft"] == 8
        assert helpers.fetch_stop(api, state["stop_id"])["safety_state"] == "SAFETY_DRAFT"

    def test_fence_between_the_floor_and_the_rigging_limit_certifies(
        self,
        api: ApiClient,
        safety_author_headers: Dict[str, str],
        safety_certifier_headers: Dict[str, str],
    ) -> None:
        """§3.5: "`catch_fence_height_ft` must be at least `required_catch_fence_height_ft` and at the same time no greater than the booked venue's `catch_fence_max_height_ft`, or `ERR_CATCH_FENCE_INSUFFICIENT`"

        §3.5: "On success `certified_by_user_id` is set to the caller, and the stop's `safety_state` moves from `SAFETY_REVIEW` to `SAFETY_CERTIFIED`, with the posture recomputed — which is the moment a stop can first become `OPEN`."

        §3.5: "The plan's `safety_cost_cents` is the provisioning bill that later flows into settlement: each ALS medic costs 45,000 cents, each BLS medic 28,000 cents, each ambulance 120,000 cents, and each linear foot of barrier 350 cents, and the cost is the sum of `medical_als_staff_count`, `medical_bls_staff_count`, `ambulance_count` and `barrier_linear_feet` each multiplied by its own rate."

        Design: Corner/validations/corner_validation_catch_fence_requirement_tracks_another_entity_s_rows
        """
        state = self._stop_with_light_entry_and_draft_plan(api, catch_fence_height_ft=8)
        self._enter_heavy_rig(api, state)
        plan_id = state["plan_id"]

        submitted = validate_success(
            api.submit_safety_plan(plan_id, headers=safety_author_headers),
            expected_status=200,
        )
        assert submitted["state"] == "SUBMITTED"
        assert submitted["required_catch_fence_height_ft"] == 8

        certified = validate_success(
            api.certify_safety_plan(
                plan_id,
                payload=F.make_certify_payload(),
                headers=safety_certifier_headers,
            ),
            expected_status=200,
        )
        assert certified["state"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == users.SAFETY_CERTIFIER_USER_ID
        # 1 ALS, 2 BLS, 1 ambulance and 1,200 feet of barrier.
        assert certified["safety_cost_cents"] == 641000
        assert (
            helpers.fetch_stop(api, state["stop_id"])["safety_state"]
            == "SAFETY_CERTIFIED"
        )


class TestSeasonWindowOutranksTheLeadTime:
    """Both calendar checks run at proposal time, and the season window is answered first."""

    def _season_and_venue(self, api: ApiClient) -> Dict[str, Any]:
        """A season running 2026-10-01 to 2027-03-31 and one building to book."""
        state = helpers.create_season(api)
        state.update(helpers.create_venue(api))
        return state

    def test_booking_at_exactly_the_lead_time_boundary_is_admitted(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§3.1: "The `tour_date` must be at least 45 whole days after the current logical clock's date, or the proposal is rejected with `ERR_BOOKING_LEAD_TIME`."

        §3.1: "A fresh booking opens in `state` `TERMS_PROPOSED` with `negotiation_round` at 1, `terms_source` at `PROMOTER`, and `last_counter_by_user_id`, `confirmed_at` and `withdraw_reason` all null; the season's `booking_count` rises by one."

        Design: Corner/validations/corner_validation_season_window_outranks_the_booking_lead_time
        """
        state = self._season_and_venue(api)
        helpers.set_clock(api, "2026-09-30T00:00:00Z")

        booking = validate_success(
            api.create_venue_booking(
                F.make_venue_booking_payload(
                    state["season_id"], state["venue_id"], tour_date="2026-11-14"
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        assert booking["state"] == "TERMS_PROPOSED"
        assert booking["tour_date"] == "2026-11-14"

        _rows, meta = validate_paginated(
            api.list_venue_bookings(
                params={"season_id": state["season_id"]}, headers=promoter_headers
            )
        )
        assert meta["total_count"] == 1
        assert helpers.fetch_season(api, state["season_id"])["booking_count"] == 1

    def test_booking_one_day_short_of_the_lead_time_is_refused(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§3.1: "The `tour_date` must be at least 45 whole days after the current logical clock's date, or the proposal is rejected with `ERR_BOOKING_LEAD_TIME`."

        Design: Corner/validations/corner_validation_season_window_outranks_the_booking_lead_time
        """
        state = self._season_and_venue(api)
        helpers.set_clock(api, "2026-10-01T00:00:00Z")

        # The same date that cleared from 2026-09-30 is only 44 days out from 2026-10-01.
        response = api.create_venue_booking(
            F.make_venue_booking_payload(
                state["season_id"], state["venue_id"], tour_date="2026-11-14"
            ),
            headers=promoter_headers,
        )
        validate_error(response, ApiErrorId.ERR_BOOKING_LEAD_TIME, expected_status=422)

        _rows, meta = validate_paginated(
            api.list_venue_bookings(
                params={"season_id": state["season_id"]}, headers=promoter_headers
            )
        )
        assert meta["total_count"] == 0
        assert helpers.fetch_season(api, state["season_id"])["booking_count"] == 0

    def test_date_after_the_season_end_is_refused_although_the_lead_time_holds(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§3.1: "The `tour_date` must fall on or between the season's `season_start_date` and `season_end_date`, or the proposal is rejected with `ERR_DATE_OUTSIDE_SEASON`."

        Design: Corner/validations/corner_validation_season_window_outranks_the_booking_lead_time
        """
        state = self._season_and_venue(api)
        helpers.set_clock(api, "2026-10-01T00:00:00Z")

        response = api.create_venue_booking(
            F.make_venue_booking_payload(
                state["season_id"], state["venue_id"], tour_date="2027-04-15"
            ),
            headers=promoter_headers,
        )
        validate_error(response, ApiErrorId.ERR_DATE_OUTSIDE_SEASON, expected_status=422)

        _rows, meta = validate_paginated(
            api.list_venue_bookings(
                params={"season_id": state["season_id"]}, headers=promoter_headers
            )
        )
        assert meta["total_count"] == 0
        assert helpers.fetch_season(api, state["season_id"])["booking_count"] == 0

    def test_date_outside_the_season_outranks_the_lead_time_when_both_fail(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """§2.10: "Where several rules could reject the same request, they are evaluated in a fixed order and the first failure determines the response."

        §2.10: "`ERR_DATE_OUTSIDE_SEASON` (422) — booking creation only."

        §2.10: "`ERR_BOOKING_LEAD_TIME` (422) — booking creation only."

        Design: Corner/validations/corner_validation_season_window_outranks_the_booking_lead_time
        """
        state = self._season_and_venue(api)
        helpers.set_clock(api, "2026-10-01T00:00:00Z")

        # 2026-09-15 sits before the season opens and is also in the clock's past,
        # so both calendar checks would reject it.
        response = api.create_venue_booking(
            F.make_venue_booking_payload(
                state["season_id"], state["venue_id"], tour_date="2026-09-15"
            ),
            headers=promoter_headers,
        )
        error = validate_error(
            response, ApiErrorId.ERR_DATE_OUTSIDE_SEASON, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_BOOKING_LEAD_TIME.value

        _rows, meta = validate_paginated(
            api.list_venue_bookings(
                params={"season_id": state["season_id"]}, headers=promoter_headers
            )
        )
        assert meta["total_count"] == 0
        assert helpers.fetch_season(api, state["season_id"])["booking_count"] == 0
