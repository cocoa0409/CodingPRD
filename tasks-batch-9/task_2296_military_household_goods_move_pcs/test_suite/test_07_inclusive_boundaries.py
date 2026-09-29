"""Inclusive boundaries: day 270 of a claim, an exact pool fill and a deadline dispatch."""

import pytest

from test_helpers import (
    ADMIN,
    COUNSELOR,
    add_claim_item,
    api_client,
    award_payload,
    capacity_block_version,
    create_capacity_block,
    disposition_item,
    dispatch_notification_payload,
    find_notification,
    get_success_data,
    open_claim,
    pack_shipment,
    pickup_shipment,
    read_capacity_block,
    read_claim,
    read_shipment,
    review_claim,
    room_estimates,
    set_clock,
    settle_claim,
    setup_awarded_shipment,
    setup_booked_shipment,
    setup_delivered_shipment,
    submit_claim,
    survey_shipment,
    validate_success,
)

ELECTRONICS_ITEM = {
    "category": "ELECTRONICS",
    "age_years": 3.0,
    "high_value_inventory_documented": True,
}


def _two_claims_filed_either_side_of_day_270():
    """Two identical damage claims, one filed on day 270 and one on day 271."""
    scenario = setup_delivered_shipment(weigh_date="2026-08-17T00:00:00Z")
    set_clock("2026-09-01T00:00:00Z")

    on_time = open_claim(scenario, "2026-09-01T00:00:00Z", claim_type="DAMAGE")
    item_on = add_claim_item(scenario, on_time["id"], 4200.00, **ELECTRONICS_ITEM)
    late = open_claim(scenario, "2026-09-01T00:00:00Z", claim_type="DAMAGE")
    item_late = add_claim_item(scenario, late["id"], 4200.00, **ELECTRONICS_ITEM)

    set_clock("2027-05-17T00:00:00Z")
    submitted_on_time = submit_claim(scenario, on_time["id"])
    set_clock("2027-05-18T00:00:00Z")
    submitted_late = submit_claim(scenario, late["id"])

    review_claim(on_time["id"])
    review_claim(late["id"])
    disposition_item(item_on["id"], "ALLOWED")
    disposition_item(item_late["id"], "ALLOWED")
    settle_claim(on_time["id"])
    settle_claim(late["id"])

    return {
        "on_time": read_claim(on_time["id"]),
        "late": read_claim(late["id"]),
        "submitted_on_time": submitted_on_time,
        "submitted_late": submitted_late,
    }


def _award_that_exactly_fills_the_general_pool():
    """A 5,100 pound shipment awarded to a block whose general pool is 5,100 pounds."""
    scenario = setup_booked_shipment(
        order_overrides={"report_no_later_than_date": "2026-11-01T00:00:00Z"},
        shipment_overrides={
            "requested_pack_date": "2026-10-06T00:00:00Z",
            "requested_pickup_date": "2026-10-07T00:00:00Z",
            "requested_delivery_date": "2026-10-14T00:00:00Z",
        },
    )
    scenario["shipment"] = survey_shipment(
        scenario, room_estimates=room_estimates(400.0, 200.5, 93.25)
    )
    scenario["block"] = create_capacity_block(
        scenario["tsp"]["id"],
        week_start_date="2026-10-05T00:00:00Z",
        total_capacity_lbs=6000,
        short_notice_reserve_pct=0.15,
    )
    scenario["award_response"] = api_client.create_award(
        scenario["block"]["id"],
        award_payload(
            scenario["shipment"]["id"],
            capacity_block_version(scenario["block"]["id"]),
        ),
        ADMIN,
    )
    return scenario


def _two_obligations_dispatched_around_their_deadlines():
    """A pack obligation dispatched at its deadline and a pickup one dispatched later."""
    scenario = setup_awarded_shipment()

    set_clock("2026-08-05T00:00:00Z")
    pack_shipment(scenario, pack_date="2026-08-15T00:00:00Z")
    pack_obligation = find_notification(
        scenario["shipment"]["id"], "PACK_DATE_CONFIRMED"
    )

    set_clock("2026-08-08T00:00:00Z")
    pickup_shipment(scenario, actual_pickup_date="2026-08-17T00:00:00Z")
    pickup_obligation = find_notification(
        scenario["shipment"]["id"], "PICKUP_CONFIRMED"
    )

    dispatched_pack = get_success_data(
        api_client.dispatch_notification(
            pack_obligation["id"], dispatch_notification_payload("EMAIL"), COUNSELOR
        )
    )
    set_clock("2026-08-09T02:30:00Z")
    dispatched_pickup = get_success_data(
        api_client.dispatch_notification(
            pickup_obligation["id"], dispatch_notification_payload("SMS"), COUNSELOR
        )
    )
    return pack_obligation, dispatched_pack, pickup_obligation, dispatched_pickup


class TestClaimFiledOnDayTwoHundredSeventy:
    """Nine months to the day still buys full replacement value."""

    def test_day_two_hundred_seventy_keeps_full_replacement_value(self):
        """Filed 270 days after delivery, the electronics item pays its full 4,200.00.

        "at most 270 days — filing within nine months of delivery, boundary inclusive —
        earns `FULL_REPLACEMENT_VALUE`"

        Design: Difficulty/boundary_precision_check/claim_filed_on_day_270_keeps_full_replacement_value
        """
        claims = _two_claims_filed_either_side_of_day_270()

        assert claims["on_time"]["filing_window_days"] == 270
        assert claims["on_time"]["settlement_basis"] == "FULL_REPLACEMENT_VALUE"
        assert claims["on_time"]["settlement_total_usd"] == pytest.approx(4200.00, abs=0.01)

    def test_day_two_hundred_seventy_one_falls_to_depreciated_value(self):
        """One day later the same item pays 2,940.00 after three years of depreciation.

        "more than 270 days but at most 730 earns `DEPRECIATED_VALUE`"

        Design: Difficulty/boundary_precision_check/claim_filed_on_day_270_keeps_full_replacement_value
        """
        claims = _two_claims_filed_either_side_of_day_270()

        assert claims["late"]["filing_window_days"] == 271
        assert claims["late"]["settlement_basis"] == "DEPRECIATED_VALUE"
        assert claims["late"]["settlement_total_usd"] == pytest.approx(2940.00, abs=0.01)

    def test_both_filings_are_inside_the_two_year_filing_window(self):
        """Neither filing is barred, so both claims reach settlement.

        "the logical clock must be no later than 730 days — two years — after the
        shipment's `delivery_date`, a later filing being refused with
        `ERR_CLAIM_FILING_WINDOW_EXPIRED`"

        Design: Difficulty/boundary_precision_check/claim_filed_on_day_270_keeps_full_replacement_value
        """
        claims = _two_claims_filed_either_side_of_day_270()

        assert claims["submitted_on_time"]["status"] == "SUBMITTED"
        assert claims["submitted_late"]["status"] == "SUBMITTED"
        assert claims["on_time"]["status"] == "SETTLED"
        assert claims["late"]["status"] == "SETTLED"


class TestAwardExactlyFillingTheGeneralPool:
    """An award that consumes the pool to the pound is accepted, not refused."""

    def test_the_block_publishes_a_pool_the_shipment_matches_exactly(self):
        """A non-peak 6,000 pound week reserves 900 pounds and offers 5,100.

        "`general_pool_lbs` is `total_capacity_lbs` multiplied by one minus
        `effective_reserve_pct`, with the fraction discarded — rounded down to a whole
        pound — and `short_notice_pool_lbs` is whatever remains, that is,
        `total_capacity_lbs` less `general_pool_lbs`."

        Design: Difficulty/boundary_precision_check/award_exactly_filling_general_pool_is_accepted
        """
        scenario = _award_that_exactly_fills_the_general_pool()

        assert scenario["shipment"]["estimated_gross_lbs"] == 5100
        assert scenario["shipment"]["billable_weight_lbs"] == 5100
        assert scenario["shipment"]["is_short_notice"] is False
        assert scenario["shipment"]["peak_season"] is False

        block = read_capacity_block(scenario["block"]["id"])
        assert block["effective_reserve_pct"] == pytest.approx(0.15, abs=0.0001)
        assert block["general_pool_lbs"] == 5100
        assert block["short_notice_pool_lbs"] == 900

    def test_the_exact_fill_is_accepted_and_committed_to_the_general_pool(self):
        """5,100 pounds do not strictly exceed a 5,100 pound remainder.

        "only the general pool is available: the pounds are compared with
        `general_pool_lbs` less `committed_general_lbs`, and when the pounds strictly
        exceed that general remainder the award fails"

        Design: Difficulty/boundary_precision_check/award_exactly_filling_general_pool_is_accepted
        """
        scenario = _award_that_exactly_fills_the_general_pool()

        validate_success(scenario["award_response"], 200)
        block = read_capacity_block(scenario["block"]["id"])
        assert block["committed_general_lbs"] == 5100
        assert block["committed_short_notice_lbs"] == 0
        assert block["committed_lbs"] == 5100
        assert read_shipment(scenario["shipment"]["id"])["capacity_block_id"] == block["id"]

    def test_the_block_stays_open_below_the_ninety_percent_threshold(self):
        """5,100 committed pounds sit under the 5,400 pound restriction line.

        "Failing that, it becomes `RESTRICTED` when `committed_lbs` has reached or passed
        ninety percent of `total_capacity_lbs` — the threshold being ninety percent of the
        total with the fraction discarded — or when the owning provider is on
        `PROBATION`."

        Design: Difficulty/boundary_precision_check/award_exactly_filling_general_pool_is_accepted
        """
        scenario = _award_that_exactly_fills_the_general_pool()

        assert read_capacity_block(scenario["block"]["id"])["status"] == "OPEN"


class TestDispatchExactlyAtTheDeadline:
    """The dispatch boundary is inclusive on the deadline instant and strict after it."""

    def test_the_pack_obligation_is_due_seventy_two_hours_after_its_trigger(self):
        """Packing on 5 August owes the member a notice by 8 August.

        "`due_by` is `trigger_event_at` advanced by `sla_hours` hours."

        Design: Difficulty/boundary_precision_check/notification_dispatched_exactly_at_due_by_is_on_time
        """
        pack_obligation, _, _, _ = _two_obligations_dispatched_around_their_deadlines()

        assert pack_obligation["sla_hours"] == 72
        assert pack_obligation["trigger_event_at"] == "2026-08-05T00:00:00Z"
        assert pack_obligation["due_by"] == "2026-08-08T00:00:00Z"

    def test_dispatch_exactly_at_the_deadline_counts_as_sent(self):
        """Sent at the very instant it fell due, the obligation is not late at all.

        "Dispatching exactly at `due_by` yields `SENT`; one second later yields `LATE`."

        Design: Difficulty/boundary_precision_check/notification_dispatched_exactly_at_due_by_is_on_time
        """
        _, dispatched_pack, _, _ = _two_obligations_dispatched_around_their_deadlines()

        assert dispatched_pack["status"] == "SENT"
        assert dispatched_pack["sent_at"] == "2026-08-08T00:00:00Z"
        assert dispatched_pack["hours_late"] == pytest.approx(0.00, abs=0.01)
        assert dispatched_pack["channel"] == "EMAIL"

    def test_dispatch_after_the_deadline_counts_the_hours_lost(self):
        """A notice due at midnight and sent at half past two is 2.50 hours late.

        "when the clock reads strictly after `due_by` it moves `PENDING → LATE` and
        `hours_late` is the elapsed time from `due_by` to `sent_at` expressed in hours and
        rounded half up to two decimal places"

        Design: Difficulty/boundary_precision_check/notification_dispatched_exactly_at_due_by_is_on_time
        """
        _, _, pickup_obligation, dispatched_pickup = (
            _two_obligations_dispatched_around_their_deadlines()
        )

        assert pickup_obligation["sla_hours"] == 24
        assert pickup_obligation["due_by"] == "2026-08-09T00:00:00Z"
        assert dispatched_pickup["status"] == "LATE"
        assert dispatched_pickup["hours_late"] == pytest.approx(2.50, abs=0.01)
        assert dispatched_pickup["channel"] == "SMS"
