"""Ledger reads, rate and fee constants, aggregate exclusion and the supersede link."""

import pytest

from test_helpers import (
    COUNSELOR,
    EXAMINER,
    EXAMINER_ALT,
    api_client,
    award_shipment,
    cancel_shipment_payload,
    create_capacity_block,
    create_shipment_payload,
    disposition_item,
    dispute_weight_payload,
    entitlement_version,
    get_success_data,
    read_capacity_block,
    read_entitlement,
    read_shipment,
    read_tsp,
    record_actual_weight,
    review_claim,
    reweigh_payload,
    room_estimates,
    set_clock,
    setup_booked_shipment,
    setup_delivered_shipment_with_claim,
    setup_surveyed_shipment,
    setup_second_shipment,
    settle_claim,
    submit_claim,
    survey_payload,
    survey_shipment,
    validate_paginated,
    validate_success,
)

WEIGH_DATE = "2026-08-17T00:00:00Z"
FILING_CLOCK = "2026-09-01T00:00:00Z"
HIGH_VALUE_ITEMS = [
    {
        "replacement_cost_usd": 6000.00,
        "category": "ELECTRONICS",
        "age_years": 2.0,
        "item_description": "HOME THEATRE PROJECTOR",
        "high_value_inventory_documented": False,
    },
    {
        "replacement_cost_usd": 5000.00,
        "category": "ELECTRONICS",
        "age_years": 4.0,
        "item_description": "FLAT PANEL TELEVISION",
        "high_value_inventory_documented": True,
    },
]
E6_ALONE = {"dependents_count": 0, "spouse_present": False}
E5_ALONE = {"rank_code": "E5", "dependents_count": 0, "spouse_present": False}
SECOND_LOT = {
    "requested_pack_date": "2026-08-16T00:00:00Z",
    "requested_pickup_date": "2026-08-19T00:00:00Z",
    "requested_delivery_date": "2026-08-26T00:00:00Z",
}
REPLACEMENT_DATES = {
    "requested_pack_date": "2026-08-21T00:00:00Z",
    "requested_pickup_date": "2026-08-24T00:00:00Z",
    "requested_delivery_date": "2026-08-31T00:00:00Z",
}


def _ledger(entitlement_id):
    return get_success_data(api_client.get_weight_ledger(entitlement_id, COUNSELOR))


def _cancel(shipment_id, cancel_reason):
    return validate_success(
        api_client.cancel_shipment(
            shipment_id, cancel_shipment_payload(cancel_reason=cancel_reason), COUNSELOR
        ),
        200,
    )


def _two_lots_one_awarded():
    """A 5,286 pound surveyed move plus a 5,100 pound sibling awarded to a 12,000 pound week."""
    scenario = setup_surveyed_shipment()
    second = setup_second_shipment(scenario, shipment_code="SHP-C02", **SECOND_LOT)
    scenario["shipment_2"] = survey_shipment(
        scenario,
        shipment_id=second["id"],
        room_estimates=room_estimates(400.0, 200.5, 93.25),
    )
    scenario["block"] = create_capacity_block(scenario["tsp"]["id"])
    award_shipment(scenario["block"]["id"], second["id"])
    return scenario


def _claim_with_two_high_value_items():
    """A filed claim holding a 6,000.00 undocumented projector and a 5,000.00 listed television."""
    scenario = setup_delivered_shipment_with_claim(
        weigh_date=WEIGH_DATE, items=HIGH_VALUE_ITEMS
    )
    set_clock(FILING_CLOCK)
    scenario["claim"] = submit_claim(scenario, scenario["claim"]["id"])
    return scenario


def _claim_items(claim_id):
    return get_success_data(api_client.list_claim_items(claim_id, EXAMINER))


def _allow_every_item(claim_id):
    for item in _claim_items(claim_id):
        disposition_item(item["id"], "ALLOWED")


class TestExcessCostConstants:
    """The rate tier and the administrative-fee threshold at their exact boundaries."""

    def test_the_admin_fee_starts_only_once_transport_reaches_five_hundred(self):
        """499.38 of transport carries no fee; a single extra pound lifts it to exactly 500.00.

        "When the ratio is at most one tenth, the rate is 62.50 US dollars per hundredweight;
        when it is greater than one tenth but at most one quarter, the rate is 78.00; beyond
        one quarter it is 94.50."

        "The administrative fee, surfaced as `admin_fee_usd`, is zero when that transportation
        charge is below 500.00 US dollars, and otherwise six percent of the transportation
        charge rounded half up to cents"

        Design: Corner/calculations/admin_fee_threshold_crosses_at_exactly_five_hundred_transport
        """
        scenario = setup_surveyed_shipment(member_overrides=E6_ALONE)
        entitlement_id = scenario["entitlement"]["id"]
        shipment_id = scenario["shipment"]["id"]
        record_actual_weight(scenario, 10299, 1500, weigh_date=WEIGH_DATE)

        below = _ledger(entitlement_id)
        assert below["total_billable_cap_lbs"] == 8000
        assert below["charged_billable_weight_lbs"] == 8799
        assert below["excess_weight_lbs"] == 799
        assert below["excess_rate_per_cwt"] == pytest.approx(62.50, abs=0.01)
        assert below["admin_fee_usd"] == pytest.approx(0.00, abs=0.01)
        assert below["gross_excess_cost_usd"] == pytest.approx(499.38, abs=0.01)
        assert below["excess_cost_due_usd"] == pytest.approx(499.38, abs=0.01)

        get_success_data(
            api_client.dispute_weight(
                shipment_id,
                dispute_weight_payload(dispute_reason="TARE TICKET LOOKED LIGHT"),
                COUNSELOR,
            )
        )
        reweighed = validate_success(
            api_client.reweigh_shipment(
                shipment_id,
                reweigh_payload(10300, 1500, WEIGH_DATE),
                scenario["tsp_headers"],
            ),
            200,
        )
        assert reweighed["net_actual_lbs"] == 8800
        assert reweighed["billable_weight_lbs"] == 8800

        at_threshold = _ledger(entitlement_id)
        assert at_threshold["excess_weight_lbs"] == 800
        assert at_threshold["excess_pct_over"] == pytest.approx(0.10, abs=0.0001)
        assert at_threshold["excess_rate_per_cwt"] == pytest.approx(62.50, abs=0.01)
        assert at_threshold["admin_fee_usd"] == pytest.approx(30.00, abs=0.01)
        assert at_threshold["gross_excess_cost_usd"] == pytest.approx(530.00, abs=0.01)
        assert read_entitlement(entitlement_id)["status"] == "AUTHORIZED"

    def test_the_ledger_read_shows_the_whole_derivation(self):
        """An E5 charged 8,400 pounds against 7,000 is priced at the middle tier.

        "For transparency, the entitlement exposes a computed ledger read that returns,
        alongside `entitlement_id`, the whole derivation: `total_billable_cap_lbs`,
        `charged_billable_weight_lbs`, `pro_gear_excluded_total_lbs`, `excess_weight_lbs`,
        `excess_pct_over`, `excess_rate_per_cwt`, `admin_fee_usd`, `gross_excess_cost_usd`,
        `excess_cost_waived_usd`, `excess_cost_due_usd` and `contributing_shipment_count`,
        the number of shipments currently inside the inclusion set."

        Design: Corner/endpoints/weight_ledger_read_matches_the_entitlement_fields
        """
        scenario = setup_surveyed_shipment(member_overrides=E5_ALONE)
        entitlement_id = scenario["entitlement"]["id"]
        record_actual_weight(scenario, 10000, 1600, weigh_date=WEIGH_DATE)

        ledger = _ledger(entitlement_id)
        assert ledger["entitlement_id"] == entitlement_id
        assert ledger["total_billable_cap_lbs"] == 7000
        assert ledger["charged_billable_weight_lbs"] == 8400
        assert ledger["pro_gear_excluded_total_lbs"] == 0
        assert ledger["excess_weight_lbs"] == 1400
        assert ledger["excess_pct_over"] == pytest.approx(0.2, abs=0.0001)
        assert ledger["excess_rate_per_cwt"] == pytest.approx(78.00, abs=0.01)
        assert ledger["admin_fee_usd"] == pytest.approx(65.52, abs=0.01)
        assert ledger["gross_excess_cost_usd"] == pytest.approx(1157.52, abs=0.01)
        assert ledger["excess_cost_waived_usd"] == pytest.approx(0.00, abs=0.01)
        assert ledger["excess_cost_due_usd"] == pytest.approx(1157.52, abs=0.01)
        assert ledger["contributing_shipment_count"] == 1

        entitlement = read_entitlement(entitlement_id)
        assert entitlement["charged_billable_weight_lbs"] == 8400
        assert entitlement["excess_weight_lbs"] == 1400
        assert entitlement["gross_excess_cost_usd"] == pytest.approx(1157.52, abs=0.01)
        assert entitlement["excess_cost_due_usd"] == pytest.approx(1157.52, abs=0.01)
        assert entitlement["status"] == "AUTHORIZED"


class TestAggregatesAfterCancellation:
    """A cancelled shipment keeps its own pounds and leaves every total behind."""

    def test_a_cancelled_lot_drops_out_of_the_ledger_and_the_week(self):
        """The 5,100 pound sibling is cancelled: 10,386 charged pounds fall back to 5,286.

        "**First**, the owning entitlement's `charged_billable_weight_lbs`,
        `pro_gear_excluded_total_lbs`, `excess_weight_lbs`, `gross_excess_cost_usd` and
        `excess_cost_due_usd` are recomputed with this shipment now outside the inclusion set."

        "**Second**, because those pounds have also left the capacity sums, if
        `capacity_block_id` is not null that block's `committed_general_lbs`,
        `committed_short_notice_lbs` and `committed_lbs` are recomputed."

        "Cancellation also decrements the member's `active_shipment_count`."

        Design: Corner/calculations/cancelled_shipment_leaves_the_entitlement_ledger_and_capacity
        """
        scenario = _two_lots_one_awarded()
        entitlement_id = scenario["entitlement"]["id"]
        second_id = scenario["shipment_2"]["id"]
        assert scenario["shipment_2"]["estimated_gross_lbs"] == 5100

        before = _ledger(entitlement_id)
        assert before["charged_billable_weight_lbs"] == 10386
        assert before["contributing_shipment_count"] == 2

        cancelled = _cancel(second_id, "MEMBER SOLD THE SECOND LOT")
        assert cancelled["movement_status"] == "CANCELLED"

        after = _ledger(entitlement_id)
        assert after["charged_billable_weight_lbs"] == 5286
        assert after["contributing_shipment_count"] == 1
        assert after["excess_weight_lbs"] == 0

        stored = read_shipment(second_id)
        assert stored["billable_weight_lbs"] == 5100
        assert stored["billable_basis"] == "ESTIMATED"
        assert stored["cancel_reason"] == "MEMBER SOLD THE SECOND LOT"

        block = read_capacity_block(scenario["block"]["id"])
        assert block["committed_general_lbs"] == 0
        assert block["committed_short_notice_lbs"] == 0
        assert block["committed_lbs"] == 0
        assert block["status"] == "OPEN"

        member = get_success_data(
            api_client.get_service_member(scenario["member"]["id"], COUNSELOR)
        )
        assert member["active_shipment_count"] == 1

    def test_the_replacement_is_reachable_from_the_cancelled_shipment(self):
        """The reverse read is walked from the cancelled lot, and only in that direction.

        "Shipments that supersede a given cancelled shipment can be listed by following the
        self-reference in reverse."

        "A replacement shipment may then be booked naming the cancelled one as its
        `superseded_shipment_id`."

        Design: Corner/endpoints/superseding_shipment_link_resolves_the_self_reference
        """
        scenario = setup_booked_shipment()
        first_id = scenario["shipment"]["id"]
        _cancel(first_id, "ORDERS SLIPPED ONE WEEK")

        replacement = validate_success(
            api_client.create_shipment(
                create_shipment_payload(
                    scenario["order"]["id"],
                    scenario["entitlement"]["id"],
                    scenario["tsp"]["id"],
                    entitlement_version(scenario["entitlement"]["id"]),
                    shipment_code="SHP-C02",
                    superseded_shipment_id=first_id,
                    **REPLACEMENT_DATES,
                ),
                COUNSELOR,
            ),
            201,
        )
        assert replacement["superseded_shipment_id"] == first_id

        rows, meta = validate_paginated(
            api_client.list_superseding_shipments(first_id, COUNSELOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == replacement["id"]
        assert rows[0]["shipment_code"] == "SHP-C02"

        _, reverse_meta = validate_paginated(
            api_client.list_superseding_shipments(replacement["id"], COUNSELOR)
        )
        assert reverse_meta["total_count"] == 0

        _, order_meta = validate_paginated(
            api_client.list_shipments(
                COUNSELOR, params={"order_id": scenario["order"]["id"]}
            )
        )
        assert order_meta["total_count"] == 2

        member = get_success_data(
            api_client.get_service_member(scenario["member"]["id"], COUNSELOR)
        )
        assert member["active_shipment_count"] == 1


class TestSettlementAndSurveyArithmetic:
    """The high-value cap on one item, and the survey response that already carries its own totals."""

    def test_an_undocumented_high_value_item_settles_at_the_cap(self):
        """A 6,000.00 projector off the inventory sheet pays 5,000.00; the listed set pays in full.

        "an item whose `replacement_cost_usd` is 5,000.00 US dollars or more and whose
        `high_value_inventory_documented` is false has its effective cost capped at 5,000.00 —
        undocumented high-value goods are not paid above the threshold. Under
        `FULL_REPLACEMENT_VALUE`, `item_settlement_usd` is that effective cost rounded half up
        to cents, with no reduction for age."

        "starting from 100.00, deduct 5.00 points for each settled claim counted against the
        provider, deduct a further point for every 500.00 US dollars of cumulative settlement,
        round half up to two decimals, and floor the result at 0.00"

        Design: Corner/calculations/high_value_undocumented_item_is_capped_at_five_thousand
        """
        scenario = _claim_with_two_high_value_items()
        claim_id = scenario["claim"]["id"]
        assert scenario["claim"]["claimed_total_usd"] == pytest.approx(11000.00, abs=0.01)
        assert scenario["claim"]["settlement_basis"] == "FULL_REPLACEMENT_VALUE"
        assert scenario["claim"]["item_count"] == 2

        review_claim(claim_id)
        _allow_every_item(claim_id)
        settled = settle_claim(claim_id, headers=EXAMINER_ALT)
        assert settled["status"] == "SETTLED"
        assert settled["settlement_total_usd"] == pytest.approx(10000.00, abs=0.01)
        assert settled["item_count"] == 2

        by_number = {item["inventory_item_number"]: item for item in _claim_items(claim_id)}
        assert by_number["INV-0001"]["item_settlement_usd"] == pytest.approx(
            5000.00, abs=0.01
        )
        assert by_number["INV-0002"]["item_settlement_usd"] == pytest.approx(
            5000.00, abs=0.01
        )

        provider = read_tsp(scenario["tsp"]["id"])
        assert provider["settled_claim_count"] == 1
        assert provider["claim_settlement_total_usd"] == pytest.approx(10000.00, abs=0.01)
        assert provider["performance_score"] == pytest.approx(75.00, abs=0.01)
        assert provider["status"] == "ACTIVE"

    def test_the_survey_response_already_carries_the_new_billable_figures(self):
        """The surveying call itself returns 5,286 estimated and billable pounds.

        "Cascades in this system are declared, ordered and multi-level, and the server
        performs them synchronously as part of the triggering request."

        "Where the status is `ESTIMATED`, the **provisional estimated** variant applies:
        `billable_weight_lbs` is `estimated_gross_lbs` less `pro_gear_excluded_lbs`, floored
        at zero, and `billable_basis` is set to `ESTIMATED`."

        Design: Corner/consistency_model/survey_response_already_carries_the_recomputed_weight_fields
        """
        scenario = setup_booked_shipment()
        assert scenario["shipment"]["billable_basis"] == "NONE"
        assert scenario["shipment"]["billable_weight_lbs"] == 0
        assert scenario["shipment"]["estimated_gross_lbs"] is None

        surveyed = validate_success(
            api_client.survey_shipment(
                scenario["shipment"]["id"], survey_payload(), scenario["tsp_headers"]
            ),
            200,
        )
        assert surveyed["estimated_gross_lbs"] == 5286
        assert surveyed["billable_weight_lbs"] == 5286
        assert surveyed["billable_basis"] == "ESTIMATED"
        assert surveyed["movement_status"] == "SURVEYED"
        assert surveyed["weight_recon_status"] == "ESTIMATED"
        assert surveyed["pro_gear_excluded_lbs"] == 0

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 5286
        assert entitlement["excess_weight_lbs"] == 0
        assert entitlement["status"] == "AUTHORIZED"

        ledger = _ledger(scenario["entitlement"]["id"])
        assert ledger["charged_billable_weight_lbs"] == 5286
        assert ledger["contributing_shipment_count"] == 1
