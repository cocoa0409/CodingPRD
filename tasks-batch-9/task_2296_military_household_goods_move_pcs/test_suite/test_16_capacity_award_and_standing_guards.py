"""Personally procured packets, award referential guards, pool protection and standing."""

import pytest

from test_helpers import (
    ADMIN,
    COUNSELOR,
    ApiErrorId,
    api_client,
    award_payload,
    award_shipment,
    create_capacity_block,
    create_ppm_payload,
    create_shipment_payload,
    disposition_item,
    entitlement_version,
    get_success_data,
    make_tsp_coordinator_headers,
    read_capacity_block,
    read_entitlement,
    read_shipment,
    read_tsp,
    release_award_payload,
    review_claim,
    room_estimates,
    set_clock,
    settle_claim,
    setup_booked_shipment,
    setup_delivered_shipment_with_claim,
    setup_second_shipment,
    setup_second_tsp,
    setup_weighed_shipment,
    submit_claim,
    survey_shipment,
    trip_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

WEIGH_DATE = "2026-08-17T00:00:00Z"
FILING_CLOCK = "2026-09-01T00:00:00Z"
NOTICE_DATE = "2026-08-25T00:00:00Z"
E5_ALONE = {"rank_code": "E5", "dependents_count": 0, "spouse_present": False}
AUGUST_LOT = {
    "requested_pack_date": "2026-08-16T00:00:00Z",
    "requested_pickup_date": "2026-08-19T00:00:00Z",
    "requested_delivery_date": "2026-08-26T00:00:00Z",
}
NOVEMBER_LOT = {
    "requested_pack_date": "2026-11-05T00:00:00Z",
    "requested_pickup_date": "2026-11-06T00:00:00Z",
    "requested_delivery_date": "2026-11-16T00:00:00Z",
}
NOVEMBER_LOT_LATE = {
    "requested_pack_date": "2026-11-12T00:00:00Z",
    "requested_pickup_date": "2026-11-13T00:00:00Z",
    "requested_delivery_date": "2026-11-23T00:00:00Z",
}
SHORT_NOTICE_LOT = {
    "requested_pack_date": "2026-08-05T00:00:00Z",
    "requested_pickup_date": "2026-08-06T00:00:00Z",
    "requested_delivery_date": "2026-08-16T00:00:00Z",
}
SEPTEMBER_LOT = {
    "requested_pack_date": "2026-09-14T00:00:00Z",
    "requested_pickup_date": "2026-09-17T00:00:00Z",
    "requested_delivery_date": "2026-09-24T00:00:00Z",
}
LATE_REPORTING_ORDERS = {"report_no_later_than_date": "2026-12-01T00:00:00Z"}
SMALL_LOT = 40.0


def _small_survey(scenario, shipment_id, headers=None):
    """Survey a 40 cubic foot lot, which converts to 294 pounds with its uplift."""
    if headers is not None:
        return get_success_data(
            api_client.survey_shipment(
                shipment_id,
                {"estimate_method": "CUBE_X7", "room_estimates": room_estimates(SMALL_LOT)},
                headers,
            )
        )
    return survey_shipment(
        scenario, shipment_id=shipment_id, room_estimates=room_estimates(SMALL_LOT)
    )


def _award(block_id, shipment_id, version, headers=ADMIN):
    return api_client.create_award(
        block_id, award_payload(shipment_id, version), headers
    )


def _packet(shipment_id, tickets):
    return api_client.create_ppm_submission(
        shipment_id, create_ppm_payload(trip_tickets=tickets), COUNSELOR
    )


def _packets(shipment_id):
    return validate_paginated(
        api_client.list_shipment_ppm_submissions(shipment_id, COUNSELOR)
    )


def _three_shipments_and_one_block():
    """One unsurveyed lot, one surveyed 294 pound lot and a third lot booked with a rival provider."""
    scenario = setup_booked_shipment()
    scenario["second_tsp"] = setup_second_tsp()
    scenario["second_tsp_headers"] = make_tsp_coordinator_headers(
        scenario["second_tsp"]["id"]
    )

    own = setup_second_shipment(scenario, shipment_code="SHP-C02", **AUGUST_LOT)
    scenario["own_lot"] = _small_survey(scenario, own["id"])

    foreign = get_success_data(
        api_client.create_shipment(
            create_shipment_payload(
                scenario["order"]["id"],
                scenario["entitlement"]["id"],
                scenario["second_tsp"]["id"],
                entitlement_version(scenario["entitlement"]["id"]),
                shipment_code="SHP-C03",
                **AUGUST_LOT,
            ),
            COUNSELOR,
        )
    )
    scenario["foreign_lot"] = _small_survey(
        scenario, foreign["id"], headers=scenario["second_tsp_headers"]
    )

    scenario["block"] = create_capacity_block(scenario["tsp"]["id"])
    return scenario


def _restricted_november_block():
    """A 5,600 pound non-peak week taken to RESTRICTED by one 5,286 pound award."""
    scenario = setup_booked_shipment(
        order_overrides=LATE_REPORTING_ORDERS, shipment_overrides=NOVEMBER_LOT
    )
    scenario["shipment"] = survey_shipment(scenario)

    general = setup_second_shipment(scenario, shipment_code="SHP-C02", **NOVEMBER_LOT)
    scenario["general_lot"] = _small_survey(scenario, general["id"])

    rush = setup_second_shipment(scenario, shipment_code="SHP-C03", **SHORT_NOTICE_LOT)
    scenario["rush_lot"] = _small_survey(scenario, rush["id"])
    assert rush["is_short_notice"] is True

    scenario["block"] = create_capacity_block(
        scenario["tsp"]["id"],
        week_start_date="2026-11-02T00:00:00Z",
        total_capacity_lbs=5600,
        short_notice_reserve_pct=0.05,
    )
    award_shipment(scenario["block"]["id"], scenario["shipment"]["id"])
    scenario["block"] = read_capacity_block(scenario["block"]["id"])
    return scenario


def _settled_claim_of_twenty_three_thousand():
    """A documented 23,000.00 electronics loss settled against the provider."""
    scenario = setup_delivered_shipment_with_claim(
        weigh_date=WEIGH_DATE,
        notice_date=NOTICE_DATE,
        claim_overrides={"claim_type": "LOSS"},
        items=[
            {
                "replacement_cost_usd": 23000.00,
                "category": "ELECTRONICS",
                "age_years": 2.0,
                "item_description": "RECORDING STUDIO CONSOLE",
                "high_value_inventory_documented": True,
            }
        ],
    )
    claim_id = scenario["claim"]["id"]
    set_clock(FILING_CLOCK)
    scenario["claim"] = submit_claim(scenario, claim_id)
    review_claim(claim_id)
    disposition_item(scenario["claim_items"][0]["id"], "ALLOWED")
    scenario["claim"] = settle_claim(claim_id)
    return scenario


class TestPersonallyProcuredPacketGuards:
    """The method gate and the weight-ticket completeness rule."""

    def test_a_packet_needs_a_ppm_shipment_and_a_usable_ticket_pair(self):
        """The household-goods lot refuses the packet outright; two bad tickets refuse themselves.

        "A member who moves their own household submits a packet against a shipment whose
        `shipment_method` is `PPM`; against any other method the submission is refused with
        `ERR_PPM_METHOD_REQUIRED`."

        "Every ticket must be certified, must name a non-empty source, and must show a
        `full_lbs` strictly greater than its `empty_lbs`; any ticket failing that is refused
        with `ERR_WEIGHT_TICKET_PAIR_INCOMPLETE`, both at submission and again at approval."

        Design: Corner/validations/ppm_guards_reject_non_ppm_shipment_and_bad_ticket_pair
        """
        scenario = setup_booked_shipment()
        hauled = setup_second_shipment(
            scenario, shipment_code="SHP-C02", shipment_method="PPM", **AUGUST_LOT
        )
        assert hauled["shipment_method"] == "PPM"

        validate_error(
            _packet(scenario["shipment"]["id"], [trip_ticket(1, 9200, 5400)]),
            ApiErrorId.ERR_PPM_METHOD_REQUIRED.value,
            422,
        )
        _, hhg_meta = _packets(scenario["shipment"]["id"])
        assert hhg_meta["total_count"] == 0

        validate_error(
            _packet(hauled["id"], [trip_ticket(1, 5000, 5200)]),
            ApiErrorId.ERR_WEIGHT_TICKET_PAIR_INCOMPLETE.value,
            422,
        )
        validate_error(
            _packet(hauled["id"], [trip_ticket(1, 9200, 5400, certified=False)]),
            ApiErrorId.ERR_WEIGHT_TICKET_PAIR_INCOMPLETE.value,
            422,
        )

        _, ppm_meta = _packets(hauled["id"])
        assert ppm_meta["total_count"] == 0


class TestAwardReferentialGuards:
    """Three refusals on one block, then the award that the block does accept."""

    def test_the_award_path_names_the_missing_basis_the_missing_award_and_the_rival(self):
        """An unpriced lot, a release with no award behind it and a rival provider's lot.

        "the shipment's `tsp_id` must equal the block's `tsp_id`, or the award is refused with
        `ERR_SHIPMENT_TSP_MISMATCH`"

        "the shipment must already have a weight of record, meaning its `billable_basis` is
        not `NONE`, or the award is refused with `ERR_WEIGHT_BASIS_MISSING`"

        "The shipment must actually hold an award on that block — otherwise
        `ERR_AWARD_NOT_FOUND` — and its `tsp_id` must still match the block's, or
        `ERR_SHIPMENT_TSP_MISMATCH` applies."

        Design: Corner/validations/award_guards_reject_unsurveyed_and_unawarded_and_foreign_shipments
        """
        scenario = _three_shipments_and_one_block()
        block_id = scenario["block"]["id"]
        version = scenario["block"]["version"]

        validate_error(
            _award(block_id, scenario["shipment"]["id"], version),
            ApiErrorId.ERR_WEIGHT_BASIS_MISSING.value,
            409,
        )
        validate_error(
            api_client.release_award(
                block_id,
                release_award_payload(
                    scenario["own_lot"]["id"], release_reason="NEVER AWARDED"
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_AWARD_NOT_FOUND.value,
            409,
        )
        validate_error(
            _award(block_id, scenario["foreign_lot"]["id"], version),
            ApiErrorId.ERR_SHIPMENT_TSP_MISMATCH.value,
            409,
        )

        awarded = validate_success(
            _award(block_id, scenario["own_lot"]["id"], version), 200
        )
        assert awarded["billable_weight_lbs"] == 294
        assert awarded["capacity_block_id"] == block_id

        block = read_capacity_block(block_id)
        assert block["committed_general_lbs"] == 294
        assert block["committed_lbs"] == 294
        assert block["status"] == "OPEN"
        assert block["version"] == version + 1


class TestPoolProtection:
    """A restricted week that still takes rush work, and a reserve that refuses to be eaten."""

    def test_a_restricted_week_refuses_general_work_but_takes_short_notice(self):
        """5,286 committed pounds restrict the week; the 294 pound rush lot still fits.

        "it becomes `RESTRICTED` when `committed_lbs` has reached or passed ninety percent of
        `total_capacity_lbs` — the threshold being ninety percent of the total with the
        fraction discarded — or when the owning provider is on `PROBATION`."

        "A block that is `CLOSED` accepts nothing, and a block that is `RESTRICTED` accepts
        only a short-notice shipment; anything else draws `ERR_CAPACITY_BLOCK_NOT_OPEN`."

        "`general_pool_lbs` is `total_capacity_lbs` multiplied by one minus
        `effective_reserve_pct`, with the fraction discarded — rounded down to a whole pound —
        and `short_notice_pool_lbs` is whatever remains"

        Design: Corner/validations/restricted_block_refuses_general_award_but_takes_short_notice
        """
        scenario = _restricted_november_block()
        block = scenario["block"]
        assert block["peak_season"] is False
        assert block["effective_reserve_pct"] == pytest.approx(0.05, abs=0.0001)
        assert block["general_pool_lbs"] == 5320
        assert block["short_notice_pool_lbs"] == 280
        assert block["committed_general_lbs"] == 5286
        assert block["status"] == "RESTRICTED"

        validate_error(
            _award(block["id"], scenario["general_lot"]["id"], block["version"]),
            ApiErrorId.ERR_CAPACITY_BLOCK_NOT_OPEN.value,
            409,
        )

        rushed = validate_success(
            _award(block["id"], scenario["rush_lot"]["id"], block["version"]), 200
        )
        assert rushed["capacity_block_id"] == block["id"]

        after = read_capacity_block(block["id"])
        assert after["committed_short_notice_lbs"] == 294
        assert after["committed_general_lbs"] == 5286
        assert after["committed_lbs"] == 5580
        assert after["status"] == "RESTRICTED"

    def test_a_general_award_may_not_dip_into_the_reserve(self):
        """5,286 pounds fit the 6,000 pound week but not its 5,100 pound general pool.

        "when the pounds strictly exceed that general remainder the award fails — with
        `ERR_SHORT_NOTICE_RESERVE_PROTECTED` when the pounds would nevertheless have fitted
        inside `total_capacity_lbs` less `committed_lbs`, meaning the only way to accommodate
        them would be to eat into the short-notice reserve, and with `ERR_CAPACITY_EXCEEDED`
        when they would not have fitted even then."

        Design: Corner/validations/general_award_that_would_eat_the_reserve_returns_reserve_protected
        """
        scenario = setup_booked_shipment(
            order_overrides=LATE_REPORTING_ORDERS, shipment_overrides=NOVEMBER_LOT_LATE
        )
        scenario["shipment"] = survey_shipment(scenario)
        assert scenario["shipment"]["billable_weight_lbs"] == 5286

        small = setup_second_shipment(
            scenario, shipment_code="SHP-C02", **NOVEMBER_LOT_LATE
        )
        small = _small_survey(scenario, small["id"])

        block = create_capacity_block(
            scenario["tsp"]["id"],
            week_start_date="2026-11-09T00:00:00Z",
            total_capacity_lbs=6000,
        )
        assert block["general_pool_lbs"] == 5100
        assert block["short_notice_pool_lbs"] == 900

        validate_error(
            _award(block["id"], scenario["shipment"]["id"], block["version"]),
            ApiErrorId.ERR_SHORT_NOTICE_RESERVE_PROTECTED.value,
            409,
        )
        untouched = read_capacity_block(block["id"])
        assert untouched["committed_general_lbs"] == 0
        assert untouched["committed_lbs"] == 0
        assert untouched["status"] == "OPEN"

        validate_success(_award(block["id"], small["id"], block["version"]), 200)
        assert read_capacity_block(block["id"])["committed_lbs"] == 294


class TestStandingBlocksNewWork:
    """A suspended ledger and a suspended provider each refuse the next booking."""

    def test_a_suspended_ledger_takes_no_further_shipment(self):
        """3,005.10 owed suspends the E5 ledger, and the state gate answers before the version gate.

        "While suspended, the ledger takes no new commitments: booking another shipment or
        awarding capacity is refused with `ERR_ENTITLEMENT_SUSPENDED`."

        "The two are mutually exclusive by construction, so exactly one of
        `ERR_ENTITLEMENT_NOT_AUTHORIZED` and `ERR_ENTITLEMENT_SUSPENDED` can fire for any
        given entitlement."

        Design: Corner/validations/second_shipment_while_entitlement_suspended_returns_entitlement_suspended
        """
        scenario = setup_weighed_shipment(
            12000,
            2000,
            weigh_date=WEIGH_DATE,
            member_overrides=E5_ALONE,
            block_overrides={"total_capacity_lbs": 20000},
        )
        stale_version = scenario["entitlement"]["version"]

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["total_billable_cap_lbs"] == 7000
        assert entitlement["status"] == "SUSPENDED"
        assert entitlement["suspension_reason"] == "EXCESS_COST_UNPAID"
        assert entitlement["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)
        assert entitlement["version"] > stale_version

        validate_error(
            api_client.create_shipment(
                create_shipment_payload(
                    scenario["order"]["id"],
                    scenario["entitlement"]["id"],
                    scenario["tsp"]["id"],
                    stale_version,
                    shipment_code="SHP-C02",
                    **AUGUST_LOT,
                ),
                COUNSELOR,
            ),
            ApiErrorId.ERR_ENTITLEMENT_SUSPENDED.value,
            409,
        )

        _, meta = validate_paginated(
            api_client.list_order_shipments(scenario["order"]["id"], COUNSELOR)
        )
        assert meta["total_count"] == 1

    def test_a_suspended_provider_takes_no_further_shipment(self):
        """A 23,000.00 settlement drops the provider to 49.00, closes its week and bars new work.

        "starting from 100.00, deduct 5.00 points for each settled claim counted against the
        provider, deduct a further point for every 500.00 US dollars of cumulative settlement,
        round half up to two decimals, and floor the result at 0.00"

        "when the provider lands on `SUSPENDED`, every block of that provider whose `status`
        is `OPEN` or `RESTRICTED` moves to `CLOSED`."

        "a `SUSPENDED` provider takes no new work, so booking a shipment with that provider or
        awarding capacity to one of its blocks is refused with `ERR_TSP_NOT_ACTIVE`, while
        `PROBATION` remains eligible."

        Design: Corner/validations/suspended_tsp_returns_tsp_not_active_on_new_shipment
        """
        scenario = _settled_claim_of_twenty_three_thousand()
        assert scenario["claim"]["settlement_basis"] == "FULL_REPLACEMENT_VALUE"
        assert scenario["claim"]["filing_window_days"] == 12
        assert scenario["claim"]["settlement_total_usd"] == pytest.approx(
            23000.00, abs=0.01
        )

        provider = read_tsp(scenario["tsp"]["id"])
        assert provider["performance_score"] == pytest.approx(49.00, abs=0.01)
        assert provider["status"] == "SUSPENDED"

        block = read_capacity_block(scenario["block"]["id"])
        assert block["status"] == "CLOSED"
        assert block["committed_lbs"] == 4700

        validate_error(
            api_client.create_shipment(
                create_shipment_payload(
                    scenario["order"]["id"],
                    scenario["entitlement"]["id"],
                    scenario["tsp"]["id"],
                    entitlement_version(scenario["entitlement"]["id"]),
                    shipment_code="SHP-C02",
                    **SEPTEMBER_LOT,
                ),
                COUNSELOR,
            ),
            ApiErrorId.ERR_TSP_NOT_ACTIVE.value,
            409,
        )

        assert read_shipment(scenario["shipment"]["id"])["movement_status"] == "DELIVERED"
