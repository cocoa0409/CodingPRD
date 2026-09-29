"""Two interval regimes that behave in deliberately opposite ways.

Accounting periods are half-open with exclusive occupancy; redemption holds are closed at
both ends, may overlap freely, and are capped only by the aggregate they reserve.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_HOLD_CAPACITY_EXCEEDED, ERR_PERIOD_OVERLAP
from test_helpers.factories import liability_period_payload, redemption_hold_payload
from test_helpers.fixtures import (
    create_rack,
    create_store,
    funded_physical_card,
    open_period,
    parse_instant,
    place_hold,
    read_card,
    total_count,
)
from test_helpers.test_users import (
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
)


AUG = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
SEP = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
STRADDLE = ("2026-08-31T00:00:00Z", "2026-09-15T00:00:00Z")


class TestPeriodHalfOpenOccupancy:
    """"Both comparisons being strict makes adjacency legal"."""

    def test_two_back_to_back_periods_touching_at_one_instant_both_exist(self, client):
        """"a period ending at one instant and another beginning at exactly that same
        instant do not overlap, and both may exist", the shared instant belonging only to
        the later period because "the start instant belongs to the period, the end instant
        does not".

        Design: Difficulty/resource_temporal_overlap/liability_period_half_open_adjacency_allowed_overlap_rejected
        """
        assert total_count(client.list_liability_periods(make_liability_accountant_headers())) == 0

        august = open_period(client, AUG[0], AUG[1], label="2026-08")
        september = open_period(client, SEP[0], SEP[1], label="2026-09")

        assert august["state"] == "OPEN"
        assert september["state"] == "OPEN"
        assert parse_instant(august["period_end"]) == parse_instant("2026-09-01T00:00:00Z")
        assert parse_instant(september["period_start"]) == parse_instant("2026-09-01T00:00:00Z")
        assert parse_instant(september["period_start"]) == parse_instant(august["period_end"])

    def test_a_straddling_period_is_refused_as_an_overlap(self, client):
        """"Two periods overlap when the candidate's start falls strictly before the existing
        period's end and the existing period's start falls strictly before the candidate's
        end", and such a candidate is "refused with ERR_PERIOD_OVERLAP".

        Design: Difficulty/resource_temporal_overlap/liability_period_half_open_adjacency_allowed_overlap_rejected
        """
        open_period(client, AUG[0], AUG[1], label="2026-08")
        open_period(client, SEP[0], SEP[1], label="2026-09")

        response = client.create_liability_period(
            liability_period_payload(STRADDLE[0], STRADDLE[1], label="2026-08-straddle"),
            make_liability_accountant_headers(),
        )

        assert response.status_code == 409, response.text
        validate_error(response, ERR_PERIOD_OVERLAP, 409)

    def test_the_refused_period_was_never_persisted(self, client):
        """A rejected request "is rejected with that rule's error and no later rule is
        evaluated", leaving the calendar holding only the two legal adjacent periods.

        Design: Difficulty/resource_temporal_overlap/liability_period_half_open_adjacency_allowed_overlap_rejected
        """
        open_period(client, AUG[0], AUG[1], label="2026-08")
        open_period(client, SEP[0], SEP[1], label="2026-09")

        client.create_liability_period(
            liability_period_payload(STRADDLE[0], STRADDLE[1], label="2026-08-straddle"),
            make_liability_accountant_headers(),
        )

        accountant = make_liability_accountant_headers()
        assert total_count(client.list_liability_periods(accountant)) == 2
        assert total_count(client.list_liability_periods(accountant, {"state": "OPEN"})) == 2


class TestHoldAggregateCapacity:
    """"Overlapping holds on one card are perfectly legal; what is capped is their sum"."""

    def _card_with_two_holds(self, client):
        """A 10000-cent card carrying 4000 over [00:00, 06:00] and 5000 over [12:00, 18:00],
        the card version re-read before each hold for its stale-version guard."""
        store = create_store(client, name="Metro Wholesale", region_code="NE", address_line="500 Metro Pkwy")
        rack = create_rack(client, store["id"], rack_label="RACK-M1", expected_card_count=11)
        card = funded_physical_card(client, 10000, store=store, rack=rack)["card"]
        hold1 = place_hold(
            client, card["id"], 4000, "2026-08-01T00:00:00Z", "2026-08-01T06:00:00Z",
            read_card(client, card["id"])["version"],
        )
        hold2 = place_hold(
            client, card["id"], 5000, "2026-08-01T12:00:00Z", "2026-08-01T18:00:00Z",
            read_card(client, card["id"])["version"],
        )
        return {"card_id": card["id"], "hold1": hold1, "hold2": hold2}

    def test_two_disjoint_holds_reserve_without_spending(self, client):
        """"held_amount_cents is the sum of the amounts of the counted holds, and
        available_balance_cents is the current balance minus the held amount, floored at
        zero", while a hold "does not move current_balance_cents".

        Design: Difficulty/resource_temporal_overlap/redemption_hold_aggregate_capacity_over_closed_intervals
        """
        world = self._card_with_two_holds(client)

        assert world["hold1"]["state"] == "ACTIVE"
        assert world["hold2"]["state"] == "ACTIVE"
        card = read_card(client, world["card_id"])
        assert card["held_amount_cents"] == 9000
        assert card["available_balance_cents"] == 1000
        assert card["current_balance_cents"] == 10000

    def test_a_bridging_hold_must_fit_under_the_sum_of_both_it_touches(self, client):
        """"a short hold that bridges two otherwise-disjoint holds must fit under the sum of
        both — a pairwise check would wrongly wave it through", so 2000 on top of 9000 is
        refused with ERR_HOLD_CAPACITY_EXCEEDED.

        Design: Difficulty/resource_temporal_overlap/redemption_hold_aggregate_capacity_over_closed_intervals
        """
        world = self._card_with_two_holds(client)
        version = read_card(client, world["card_id"])["version"]

        response = client.create_redemption_hold(
            world["card_id"],
            redemption_hold_payload(2000, "2026-08-01T06:00:00Z", "2026-08-01T12:00:00Z", version),
            make_pos_associate_headers(),
        )

        assert response.status_code == 422, response.text
        validate_error(response, ERR_HOLD_CAPACITY_EXCEEDED, 422)

    def test_a_candidate_that_exactly_exhausts_the_balance_is_accepted(self, client):
        """"The comparison is strict, so a candidate that exactly exhausts the balance is
        accepted and drives available_balance_cents to exactly 0; one cent more is refused"
        — and the refused attempt was not a mutation, so the same card version still works.

        Design: Difficulty/resource_temporal_overlap/redemption_hold_aggregate_capacity_over_closed_intervals
        """
        world = self._card_with_two_holds(client)
        version = read_card(client, world["card_id"])["version"]
        client.create_redemption_hold(
            world["card_id"],
            redemption_hold_payload(2000, "2026-08-01T06:00:00Z", "2026-08-01T12:00:00Z", version),
            make_pos_associate_headers(),
        )

        third = place_hold(
            client, world["card_id"], 1000, "2026-08-01T06:00:00Z", "2026-08-01T12:00:00Z", version
        )

        assert third["state"] == "ACTIVE"
        assert third["amount_cents"] == 1000
        card = read_card(client, world["card_id"])
        assert card["held_amount_cents"] == 10000
        assert card["available_balance_cents"] == 0
        assert card["current_balance_cents"] == 10000
        active = client.list_card_redemption_holds(
            world["card_id"], make_platform_admin_headers(), {"state": "ACTIVE"}
        )
        assert total_count(active) == 3
