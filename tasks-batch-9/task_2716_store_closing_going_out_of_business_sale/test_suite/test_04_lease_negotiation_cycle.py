"""The bounded offer/counter cycle of a lease disposition.

Sending an offer and recording a counter move the disposition back and forth
between two states it has already occupied, so what stops the negotiation is the
round counter rather than the state.
"""
from test_helpers import (
    ApiErrorId,
    add_inventory_lot,
    add_store,
    api_client,
    approve_engagement,
    assert_lease_disposition,
    create_engagement,
    create_jurisdiction,
    make_consultant_headers,
    open_lease_disposition,
    pin_clock,
    record_landlord_response,
    send_lease_offer,
    submit_engagement,
    validate_error,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
WHARF_LEASE = {
    "landlord_name": "Wharf Holdings", "surrender_deadline_date": "2026-11-10",
    "daily_holdover_rate_cents": 25000, "rent_arrears_cents": 400000,
    "cam_arrears_cents": 150000, "restoration_cost_cents": 600000,
    "fixture_reserve_price_cents": 900000, "surrender_credit_cents": 0,
}


def _read_disposition(disposition_id):
    return validate_success(
        api_client.get_lease_disposition(disposition_id, make_consultant_headers())
    )


def _disposition_after_three_offer_counter_loops():
    """A disposition sitting in LANDLORD_COUNTERED with all three rounds spent.

    Each of the three offers was answered with a counter, so the disposition
    entered LANDLORD_COUNTERED three separate times and the fourth offer will be
    attempted from exactly the state the second and third offers left.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(
        economics_model="FEE_BASED", guaranty_pct=0, hybrid_retailer_excess_pct=0,
        expense_responsibility="LIQUIDATOR", shared_expense_liquidator_pct=0,
        sale_start_date="2026-09-15", target_end_date="2026-11-30",
    )
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-501", address_line="3 Wharf Ln",
    )
    add_inventory_lot(
        store["id"], category="HOME", source="ORIGINAL", units_initial=500,
        unit_cost_cents=4000, unit_retail_cents=9000,
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    disposition = open_lease_disposition(store["id"], **WHARF_LEASE)
    trace = [disposition]
    trace.append(send_lease_offer(disposition["id"], 500000))
    trace.append(
        record_landlord_response(
            disposition["id"], "COUNTER", landlord_counter_amount_cents=900000
        )
    )
    trace.append(send_lease_offer(disposition["id"], 650000))
    trace.append(
        record_landlord_response(
            disposition["id"], "COUNTER", landlord_counter_amount_cents=850000
        )
    )
    trace.append(send_lease_offer(disposition["id"], 780000))
    trace.append(
        record_landlord_response(
            disposition["id"], "COUNTER", landlord_counter_amount_cents=820000
        )
    )
    return {"store": store, "disposition": disposition, "trace": trace}


class TestLeaseNegotiationCycle:
    def test_the_fourth_offer_is_refused_from_the_state_that_accepted_the_third(self):
        """Three offers are spent, so the fourth draws the round-bound refusal.

        The PRD says: "The round counter is the cycle's bound: an offer is
        permitted only while the round it would create is still within three, so
        the first, second, and third offers are accepted and the fourth is refused
        with `ERR_MAX_NEGOTIATION_ROUNDS` — the retailer gets three offers and no
        more."

        Design: Difficulty/non_linear_state_machine/lease_disposition_counter_offer_cycle_terminates_at_third_round
        """
        scenario = _disposition_after_three_offer_counter_loops()
        response = api_client.send_lease_offer(
            scenario["disposition"]["id"],
            {"offered_surrender_payment_cents": 810000},
            make_consultant_headers(),
        )
        validate_error(response, ApiErrorId.ERR_MAX_NEGOTIATION_ROUNDS.value, 409)
        after = _read_disposition(scenario["disposition"]["id"])
        assert_lease_disposition(after)
        assert after["negotiation_round"] == 3
        assert after["disposition_status"] == "LANDLORD_COUNTERED"
        assert after["offered_surrender_payment_cents"] == 780000
        assert after["landlord_counter_amount_cents"] == 820000

    def test_the_cycle_re_enters_landlord_countered_on_every_loop(self):
        """OFFER_SENT and LANDLORD_COUNTERED each occur three times over.

        The PRD says: "From `LANDLORD_COUNTERED` the consultant may send a revised
        offer, returning the disposition to `OFFER_SENT` and closing the cycle, so
        offer and counter may alternate until the third offer is spent."

        Design: Difficulty/non_linear_state_machine/lease_disposition_counter_offer_cycle_terminates_at_third_round
        """
        trace = _disposition_after_three_offer_counter_loops()["trace"]
        assert [row["disposition_status"] for row in trace] == [
            "DRAFT",
            "OFFER_SENT", "LANDLORD_COUNTERED",
            "OFFER_SENT", "LANDLORD_COUNTERED",
            "OFFER_SENT", "LANDLORD_COUNTERED",
        ]

    def test_only_sending_an_offer_consumes_a_round(self):
        """The landlord's counters leave the round counter exactly where it was.

        The PRD says: "A `COUNTER` takes the disposition `OFFER_SENT →
        LANDLORD_COUNTERED` and records `landlord_counter_amount_cents`;
        critically, a counter does not touch `negotiation_round`, because the
        counter is the landlord's move and the counter is not one of the retailer's
        three offers — only sending an offer consumes a round."

        Design: Difficulty/non_linear_state_machine/lease_disposition_counter_offer_cycle_terminates_at_third_round
        """
        trace = _disposition_after_three_offer_counter_loops()["trace"]
        assert [row["negotiation_round"] for row in trace] == [0, 1, 1, 2, 2, 3, 3]

    def test_each_offer_overwrites_the_previous_offered_figure(self):
        """The disposition carries one live offer, not a history of them.

        The PRD says: "The consultant sends an offer carrying
        `offered_surrender_payment_cents`, which is defined from `DRAFT` and from
        `LANDLORD_COUNTERED` and takes the disposition to `OFFER_SENT`,
        incrementing `negotiation_round` by 1 and recording the offered figure over
        any previous one."

        Design: Difficulty/non_linear_state_machine/lease_disposition_counter_offer_cycle_terminates_at_third_round
        """
        trace = _disposition_after_three_offer_counter_loops()["trace"]
        assert [row["offered_surrender_payment_cents"] for row in trace[1:]] == [
            500000, 500000, 650000, 650000, 780000, 780000,
        ]
        assert [row["landlord_counter_amount_cents"] for row in trace[1:]] == [
            None, 900000, 900000, 850000, 850000, 820000,
        ]
