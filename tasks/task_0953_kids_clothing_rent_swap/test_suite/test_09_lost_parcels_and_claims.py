"""Lost parcels: the liability cascade, the two variants, recovery and the claim loop."""

import pytest

from test_helpers import (
    BILLING,
    LOGISTICS,
    WAREHOUSE,
    ApiErrorId,
    assert_lost_shipment_claim,
    allocate_unit,
    create_box,
    create_open_cycle,
    create_return_shipment,
    create_shipment_payload,
    create_style,
    create_unit,
    depart_shipment,
    file_claim,
    find_charge,
    get_box_item,
    get_claim,
    get_cycle,
    get_label,
    get_member,
    get_shipment,
    get_unit,
    list_box_items,
    make_member_headers,
    mark_shipment_lost,
    mint_label,
    pack_box,
    receive_shipment,
    set_clock,
    setup_basic_delivered_scenario,
    setup_investigating_claim,
    setup_lost_return,
    setup_plan_and_member,
    ship_box,
    start_item_return,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAssessedValueRounding:
    def _two_odd_priced_units_lost(self, sku):
        scenario = setup_basic_delivered_scenario(
            plan={"tier": "CORE", "slots_per_box": 2, "swaps_per_cycle": 1,
                  "monthly_fee_cents": 5000, "discount_pct": 0},
            member={"child_size_code": "5", "protection_enrolled": False,
                    "auto_apply_credit": False},
            style={"sku": sku, "name": "Odd Priced Coat", "size_code": "5",
                   "retail_price_cents": 6001, "season": "AW",
                   "category": "OUTERWEAR"},
            unit={"acquired_at": "2026-01-01T00:00:00Z", "current_grade": "A",
                  "cycles_completed": 0},
            unit_count=2,
        )
        lost = setup_lost_return(scenario["member"],
                                 [i["id"] for i in scenario["items"]], scanned=True)
        claim = file_claim(scenario["member"]["id"], lost["return_shipment"]["id"])
        scenario["claim"] = claim
        return scenario

    def test_the_assessed_value_rounds_each_unit_before_summing(self, api):
        """PRD §3.5: "Its `assessed_value_cents` is the sum, over every unit on
        the shipment whose `state` is `LOST_IN_TRANSIT`, of that unit's style
        `retail_price_cents` multiplied by 0.55 and rounded half up to the cent
        — rounded per unit first, then summed, walking the units in ascending
        `created_at` order."
        PRD §2.7: "Whenever a total is an aggregate of per-row amounts — a
        cycle's `late_fee_cents` over its box items, a claim's
        `assessed_value_cents` over its lost units, a submission's
        `uncapped_total_cents` over its graded items — each row's amount is
        rounded to the cent *first*, and the rounded row amounts are then added.
        Summing raw fractional products and rounding once at the end is
        forbidden and produces a different total."

        Design: Difficulty/combinatorial_formula/lost_assessed_value_rounds_per_unit_then_sums
        """
        scenario = self._two_odd_priced_units_lost("SKU-ODD-6001")
        validate_success(api.investigate_claim(scenario["claim"]["id"], LOGISTICS))

        claim = get_claim(scenario["claim"]["id"])
        assert_lost_shipment_claim(claim)
        assert claim["assessed_value_cents"] == 6602
        assert claim["status"] == "INVESTIGATING"

    def test_the_scanned_variant_charges_the_household_thirty_percent(self, api):
        """PRD §3.5: "Its `member_liability_pct` is
        `LOST_LIABILITY_MEMBER_PCT_SCANNED`, 0.30, under the scanned variant,
        because the carrier is presumed to hold the parcel; and
        `LOST_LIABILITY_MEMBER_PCT_NEVER_SCANNED`, 0.60, under the never-scanned
        variant, because the parcel is presumed never to have been handed over.
        Its `member_liability_cents` is `assessed_value_cents` multiplied by
        that fraction, rounded half up."
        PRD §3.5: "The claim's `variant` resolves from `ever_scanned`: `SCANNED`
        when the parcel entered `IN_TRANSIT` at least once, `NEVER_SCANNED`
        otherwise."
        PRD §3.5: "every `INBOUND` unit moves to `LOST_IN_TRANSIT`"

        Design: Difficulty/combinatorial_formula/lost_assessed_value_rounds_per_unit_then_sums
        """
        scenario = self._two_odd_priced_units_lost("SKU-ODD-6001B")
        validate_success(api.investigate_claim(scenario["claim"]["id"], LOGISTICS))

        claim = get_claim(scenario["claim"]["id"])
        assert claim["variant"] == "SCANNED"
        assert claim["member_liability_pct"] == pytest.approx(0.30, abs=1e-9)
        assert claim["member_liability_cents"] == 1981
        for unit in scenario["units"]:
            assert get_unit(unit["id"])["state"] == "LOST_IN_TRANSIT"

    def test_the_never_scanned_variant_doubles_the_households_share(self, api):
        """PRD §3.5: "A shipment marked lost from `CREATED` — the parcel was
        handed to the carrier but never produced a departure scan — leaves
        `shipped_at` null and `ever_scanned` false. **This second edge is the
        only way a never-scanned loss can occur**"
        PRD §3.5: "On identical assessed value the never-scanned household
        therefore bears exactly double the scanned household's share."

        Design: Corner/calculations/corner_calc_lost_liability_never_scanned_variant_doubles_the_share
        """
        scenario = setup_basic_delivered_scenario(
            member={"auto_apply_credit": False},
            style={"sku": "SKU-K17-5", "name": "Never Scanned Tee", "size_code": "5",
                   "retail_price_cents": 4000},
        )
        lost = setup_lost_return(scenario["member"], [scenario["items"][0]["id"]],
                                 scanned=False)
        claim = file_claim(scenario["member"]["id"], lost["return_shipment"]["id"])
        validate_success(api.investigate_claim(claim["id"], LOGISTICS))

        shipment = get_shipment(lost["return_shipment"]["id"])
        assert shipment["ever_scanned"] is False
        assert shipment["shipped_at"] is None
        assert shipment["status"] == "LOST"

        after = get_claim(claim["id"])
        assert after["variant"] == "NEVER_SCANNED"
        assert after["assessed_value_cents"] == 2200
        assert after["member_liability_pct"] == pytest.approx(0.60, abs=1e-9)
        assert after["member_liability_cents"] == 1320


class TestLossCascade:
    def _two_cycle_world(self, sku):
        plan, member = setup_plan_and_member(
            plan={"slots_per_box": 1, "swaps_per_cycle": 1, "monthly_fee_cents": 5000},
            member={"protection_enrolled": False, "auto_apply_credit": False},
        )
        style = create_style(sku=sku, name="Winter Coat", brand_tier="PREMIUM",
                             retail_price_cents=40000, size_code="5", season="AW",
                             category="OUTERWEAR")
        unit_one = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")
        unit_two = create_unit(style["id"], acquired_at="2026-01-01T00:00:00Z")

        cycle_one = create_open_cycle(member["id"])
        box_one = create_box(cycle_one["id"])
        item_one = allocate_unit(box_one["id"], unit_id=unit_one["id"])
        pack_box(box_one["id"])
        outbound = mint_label(member["id"], "OUTBOUND")
        out_shipment = ship_box(box_one["id"], outbound["id"])
        depart_shipment(out_shipment["id"])
        receive_shipment(out_shipment["id"])

        ret = create_return_shipment(member["id"], item_count=1)
        start_item_return(member["id"], item_one["id"], ret["shipment"]["id"])
        depart_shipment(ret["shipment"]["id"])

        cycle_two = create_open_cycle(member["id"])
        box_two = create_box(cycle_two["id"])
        item_two = allocate_unit(box_two["id"], unit_id=unit_two["id"])

        return {
            "member": member, "style": style,
            "unit_one": unit_one, "unit_two": unit_two,
            "cycle_two": cycle_two, "box_two": box_two,
            "item_one": item_one, "item_two": item_two,
            "return_label": ret["label"], "return_shipment": ret["shipment"],
        }

    def test_marking_a_parcel_lost_cascades_through_label_item_and_unit(self, api):
        """PRD §3.5: "every other side effect of the two edges is identical: the
        label moves to `LOST` (from `ISSUED` on the never-scanned edge and from
        `IN_TRANSIT` on the scanned edge), every `RETURNING` box item on the
        shipment moves to `LOST` with its `settlement_status` moving to
        `LOST_CHARGED`, every `INBOUND` unit moves to `LOST_IN_TRANSIT`, and a
        charge ledger entry of `charge_type` `LOST_LIABILITY` is raised for the
        **full** assessed value — which may itself push the member `ACTIVE →
        DELINQUENT`."
        PRD §3.5: "**No claim is created automatically**; filing a claim is a
        separate, explicit act and it is the only producer of a
        `LostShipmentClaim` row."

        Design: Difficulty/transitive_cascade/lost_return_shipment_cascades_seven_hops_to_a_cancelled_allocation
        """
        world = self._two_cycle_world("SKU-COAT-40K")
        mark_shipment_lost(world["return_shipment"]["id"])
        claim = file_claim(world["member"]["id"], world["return_shipment"]["id"])

        assert get_shipment(world["return_shipment"]["id"])["status"] == "LOST"
        assert get_label(world["return_label"]["id"])["status"] == "LOST"
        first_item = get_box_item(world["item_one"]["id"])
        assert first_item["fulfillment_status"] == "LOST"
        assert first_item["settlement_status"] == "LOST_CHARGED"
        assert get_unit(world["unit_one"]["id"])["state"] == "LOST_IN_TRANSIT"
        assert get_claim(claim["id"])["status"] == "OPENED"

    def test_the_liability_charge_holds_the_second_cycle_and_frees_its_unit(self, api):
        """PRD §3.5: "a charge ledger entry of `charge_type` `LOST_LIABILITY` is
        raised for the **full** assessed value — which may itself push the
        member `ACTIVE → DELINQUENT`."
        PRD §3.1: "Falling into `DELINQUENT` cascades: every `OPEN` or
        `SWAP_CLOSED` cycle of the member moves to `HELD`; every box item of the
        member still in `ALLOCATED` moves to `CANCELLED`; each such item's
        reserved unit returns from `RESERVED` to `IN_STOCK`; a `DRAFT` box moves
        to `CANCELLED` as its allocated items are cancelled; and the member's
        `version` increments by 1."
        PRD §3.1: "An `ACTIVE` member whose outstanding balance reaches or
        exceeds `DELINQUENCY_THRESHOLD_CENTS`, which is 15000 cents, becomes
        `DELINQUENT`."

        Design: Difficulty/transitive_cascade/lost_return_shipment_cascades_seven_hops_to_a_cancelled_allocation
        """
        world = self._two_cycle_world("SKU-COAT-40K-B")
        mark_shipment_lost(world["return_shipment"]["id"])

        liability = find_charge(world["member"]["id"], "LOST_LIABILITY")
        assert liability["amount_cents"] == 22000

        member = get_member(world["member"]["id"])
        assert member["outstanding_balance_cents"] == 32000
        assert member["status"] == "DELINQUENT"

        assert get_cycle(world["cycle_two"]["id"])["status"] == "HELD"
        assert get_box_item(world["item_two"]["id"])["fulfillment_status"] == "CANCELLED"
        assert get_unit(world["unit_two"]["id"])["state"] == "IN_STOCK"
        assert validate_success(
            api.get_box(world["box_two"]["id"], WAREHOUSE)
        )["slots_free"] == 1


class TestClaimLifecycle:
    def test_a_claim_may_only_be_filed_against_a_lost_parcel(self, api):
        """PRD §3.5: "The shipment must be `LOST`; filing against anything else
        is refused with `ERR_CLAIM_SHIPMENT_NOT_LOST`."

        Design: Corner/errors/corner_err_claim_on_a_shipment_that_is_not_lost_is_rejected
        """
        _, member = setup_plan_and_member()
        label = mint_label(member["id"], "RETURN")
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(member["id"], label["id"], "RETURN", 0), LOGISTICS
            ),
            201,
        )
        depart_shipment(shipment["id"])

        resp = api.create_lost_shipment_claim({"shipment_id": shipment["id"]},
                                              make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_SHIPMENT_NOT_LOST.value, 409)
        _, meta = validate_paginated(api.list_lost_shipment_claims(
            LOGISTICS, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_filing_after_the_ten_day_window_is_refused(self, api):
        """PRD §3.5: "The filing window is `LOST_CLAIM_FILING_WINDOW_DAYS`, ten
        days, measured from the shipment's `shipped_at` — or, when `shipped_at`
        is null because the parcel never scanned, from the shipment's
        `created_at`. The resulting `deadline_at` is that base plus ten days,
        and filing is allowed **on or before** it; a later filing is refused
        with `ERR_CLAIM_WINDOW_CLOSED`."

        Design: Corner/errors/corner_err_claim_filed_after_the_window_is_rejected
        """
        _, member = setup_plan_and_member()
        label = mint_label(member["id"], "RETURN")
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(member["id"], label["id"], "RETURN", 0), LOGISTICS
            ),
            201,
        )
        depart_shipment(shipment["id"])
        mark_shipment_lost(shipment["id"])
        set_clock("2026-05-12T00:00:00Z")

        resp = api.create_lost_shipment_claim({"shipment_id": shipment["id"]},
                                              make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value, 409)

        after = get_shipment(shipment["id"])
        assert after["status"] == "LOST"
        _, meta = validate_paginated(api.list_lost_shipment_claims(
            LOGISTICS, {"limit": 10, "offset": 0}))
        assert meta["total_count"] == 0

    def test_the_investigation_information_loop_may_run_more_than_once(self, api):
        """PRD §3.5: "`INVESTIGATING` and `AWAITING_MEMBER_INFO` form a
        **bidirectional pair** that may be traversed any number of times: a
        coordinator requests information, the household answers by supplying an
        `info_note` which is appended to the claim and returns it to
        `INVESTIGATING`, and the cycle may repeat."
        PRD §3.5: "Its `assessed_value_cents` is the sum, over every unit on the
        shipment whose `state` is `LOST_IN_TRANSIT`, of that unit's style
        `retail_price_cents` multiplied by 0.55 and rounded half up to the cent
        — rounded per unit first, then summed, walking the units in ascending
        `created_at` order."

        Design: Corner/state_machines/corner_sm_claim_investigating_and_awaiting_info_round_trip
        """
        scenario = setup_basic_delivered_scenario(
            style={"sku": "SKU-SM11-5", "name": "SM Eleven Tee", "size_code": "5",
                   "retail_price_cents": 4000},
        )
        world = setup_investigating_claim(scenario["member"],
                                          [scenario["items"][0]["id"]], scanned=True)
        claim_id = world["claim"]["id"]
        member_headers = make_member_headers(scenario["member"]["id"])

        validate_success(api.request_claim_info(claim_id, LOGISTICS))
        validate_success(api.provide_claim_info(claim_id, {"info_note": "first note"},
                                                member_headers))
        validate_success(api.request_claim_info(claim_id, LOGISTICS))
        validate_success(api.provide_claim_info(claim_id, {"info_note": "second note"},
                                                member_headers))

        claim = get_claim(claim_id)
        assert claim["status"] == "INVESTIGATING"
        assert "second note" in (claim["info_note"] or "")
        assert claim["variant"] == "SCANNED"
        assert claim["assessed_value_cents"] == 2200
        assert claim["member_liability_cents"] == 660

    def test_receiving_a_lost_parcel_recovers_it_and_denies_the_claim(self, api):
        """PRD §3.5: "Receipt of a shipment whose `status` is `LOST` is permitted
        while no claim against that shipment has reached `SETTLED`; it moves the
        shipment `LOST → DELIVERED`, moves every `LOST_IN_TRANSIT` unit to
        `PROCESSING`, moves every `LOST` box item to `RECEIVED` with its
        `settlement_status` reset to `OPEN`, and denies every claim still
        `OPENED` or `INVESTIGATING` with a `denial_reason` of
        `SHIPMENT_RECOVERED`."

        Design: Corner/state_machines/corner_sm_lost_shipment_recovery_denies_the_open_claim
        """
        scenario = setup_basic_delivered_scenario(
            style={"sku": "SKU-SM10-5", "name": "SM Ten Tee", "size_code": "5",
                   "retail_price_cents": 4000},
        )
        item, unit = scenario["items"][0], scenario["units"][0]
        lost = setup_lost_return(scenario["member"], [item["id"]], scanned=True)
        claim = file_claim(scenario["member"]["id"], lost["return_shipment"]["id"])

        validate_success(api.receive_shipment(lost["return_shipment"]["id"], WAREHOUSE))

        assert get_shipment(lost["return_shipment"]["id"])["status"] == "DELIVERED"
        assert get_unit(unit["id"])["state"] == "PROCESSING"
        after_item = get_box_item(item["id"])
        assert after_item["fulfillment_status"] == "RECEIVED"
        assert after_item["settlement_status"] == "OPEN"
        after_claim = get_claim(claim["id"])
        assert after_claim["status"] == "DENIED"
        assert after_claim["denial_reason"] == "SHIPMENT_RECOVERED"
        assert validate_success(
            api.get_garment_style(scenario["style"]["id"], WAREHOUSE)
        )["units_ever_acquired"] == 1
