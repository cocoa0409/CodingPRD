"""
Money-valued calculations of the County Land Bank Authority API.

Every figure asserted here is an integer cent amount the PRD derives uniquely
from the parcel, the programme or the ledger: the two-stage maintenance-order
estimate, the four disposition price tiers with their caps and floors, the
recapture that raises an authorization and its reserve floor, and the
estimate-for-invoice swap that settles a completed order.
"""

from test_helpers import (
    ApiClient,
    assert_ledger_position,
    assert_maintenance_order,
    assert_property,
    expected_mow_estimate_cents,
    expected_reserve_floor_cents,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)
from test_helpers.test_users import DISP_1, INTAKE_1, INV_1, TREAS_1


def test_mow_estimate_rounds_the_county_overhead_half_up(api: ApiClient) -> None:
    """A 10,000 square foot mowing order is estimated at 19,703 cents because the 1,202.5-cent county overhead on the 18,500-cent subtotal rounds half up to 1,203.

    In every case the rounded line items are then summed into a subtotal, county overhead of 6.5 percent of that subtotal is computed and rounded half up as a second, separate step, and `estimated_cost_cents` is the subtotal plus that overhead.

    Design: Corner/calculations/mow_estimate_rounds_half_up_at_the_overhead_stage
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Mow Estimate Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
    )
    prop = fixtures.create_property(
        api,
        address="2010 Tulip St",
        situs_ward=3,
        lot_area_sqft=10000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    fixtures.acquire_property(
        api, prop["id"], funding_source["id"], donor_name="Tulip Street Trust"
    )
    contractor = fixtures.create_contractor(
        api,
        name="Half Cent Mowing",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )

    payload = factories.maintenance_order_payload(
        contractor["id"],
        funding_source["id"],
        fixtures.property_version(api, prop["id"]),
        work_type="MOW",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    order = validate_success(
        api.create_maintenance_order(prop["id"], payload, INV_1), 201
    )

    assert_maintenance_order(order)
    # Ten started thousand-square-foot blocks at 1,850 cents is an 18,500-cent
    # subtotal; 6.5 percent of it is 1,202.5, which rounds half up to 1,203.
    assert order["estimated_cost_cents"] == 19703
    assert order["estimated_cost_cents"] == expected_mow_estimate_cents(10000)
    assert order["status"] == "SCHEDULED"
    assert order["actual_cost_cents"] is None
    assert order["contractor_id"] == contractor["id"]
    assert order["demolition_run_id"] is None

    source = fixtures.read_funding_source(api, funding_source["id"])
    assert_ledger_position(
        source,
        authorized_cents=1000000,
        committed_cents=19703,
        disbursed_cents=0,
        available_cents=980297,
    )


def test_side_lot_assessed_cap_binds_over_the_marginal_area_price(
    api: ApiClient,
) -> None:
    """A 30,000 square foot side lot prices at 60,000 cents on area but is capped at 50,000 cents by a quarter of its 200,000-cent assessed value, and the marginal area still reports the full 25,000 square feet that were priced.

    A `SIDE_LOT` transfer starts at a base of 10,000 cents and adds 2 cents for every square foot of `lot_area_sqft` beyond the first 5,000 — the marginal area is zero when the lot is no larger than that free allowance — then caps the result at 25 percent of `assessed_value_cents` rounded half up, and finally raises it back to the 10,000-cent base if the cap pushed it below: the floor wins over the cap.

    Design: Corner/calculations/side_lot_assessed_cap_overrides_marginal_area_price
    """
    prop = fixtures.create_property(
        api,
        address="2050 Yarrow St",
        situs_ward=3,
        lot_area_sqft=30000,
        assessed_value_cents=200000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )

    quote = validate_success(api.get_price_quote(prop["id"], "SIDE_LOT", DISP_1))

    assert quote["program"] == "SIDE_LOT"
    # 10,000 base + 25,000 marginal square feet x 2 cents = 60,000 raw, capped
    # at 0.25 x 200,000 = 50,000, and the 10,000-cent base does not bind.
    assert quote["quoted_price_cents"] == 50000
    assert quote["marginal_area_sqft"] == 25000
    assert quote["assessed_cap_cents"] == 50000
    # No structure stands on the parcel, so the condition discount never applies.
    assert quote["discount_applied"] is False


def test_side_lot_assessed_cap_rounds_half_up_on_an_odd_cent(api: ApiClient) -> None:
    """A quarter of a 200,002-cent assessed value is exactly 50,000.5 cents, which rounds half up to a 50,001-cent cap rather than being truncated to 50,000.

    A `SIDE_LOT` transfer starts at a base of 10,000 cents and adds 2 cents for every square foot of `lot_area_sqft` beyond the first 5,000 — the marginal area is zero when the lot is no larger than that free allowance — then caps the result at 25 percent of `assessed_value_cents` rounded half up, and finally raises it back to the 10,000-cent base if the cap pushed it below: the floor wins over the cap.

    Design: Corner/calculations/side_lot_assessed_cap_rounds_half_up_on_odd_cent
    """
    prop = fixtures.create_property(
        api,
        address="2060 Zelkova St",
        situs_ward=3,
        lot_area_sqft=30000,
        assessed_value_cents=200002,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )

    quote = validate_success(api.get_price_quote(prop["id"], "SIDE_LOT", DISP_1))

    # The raw area price of 60,000 sits well above the cap, so the cap decides.
    assert quote["assessed_cap_cents"] == 50001
    assert quote["quoted_price_cents"] == 50001
    assert quote["marginal_area_sqft"] == 25000


def test_program_floors_bind_on_one_low_assessed_parcel(api: ApiClient) -> None:
    """On a parcel assessed at 100,000 cents the programme percentages fall under both floors, so a homeowner sale is quoted at its 100,000-cent floor and a developer request for proposals at its 500,000-cent floor.

    A `HOMEOWNER_SALE` is 55 percent of `assessed_value_cents` rounded half up, but never less than a floor of 100,000 cents. A `DEVELOPER_RFP` is 90 percent of `assessed_value_cents` rounded half up, never less than a floor of 500,000 cents.

    Design: Corner/calculations/program_floors_bind_for_homeowner_and_developer_on_same_parcel
    """
    prop = fixtures.create_property(
        api,
        address="2070 Aspen St",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=100000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )

    homeowner = validate_success(
        api.get_price_quote(prop["id"], "HOMEOWNER_SALE", DISP_1)
    )
    developer = validate_success(
        api.get_price_quote(prop["id"], "DEVELOPER_RFP", DISP_1)
    )
    community = validate_success(
        api.get_price_quote(prop["id"], "COMMUNITY_USE", DISP_1)
    )

    # 0.55 x 100,000 = 55,000 is below the 100,000-cent floor, so the floor is
    # charged, and the 55 percent figure is still reported as the assessed cap.
    assert homeowner["quoted_price_cents"] == 100000
    assert homeowner["assessed_cap_cents"] == 55000
    # 0.90 x 100,000 = 90,000 is below the 500,000-cent floor.
    assert developer["quoted_price_cents"] == 500000
    assert developer["assessed_cap_cents"] == 90000
    # The nominal community-use consideration is independent of assessed value.
    assert community["quoted_price_cents"] == 100
    assert community["assessed_cap_cents"] == 0
    assert homeowner["marginal_area_sqft"] == 0
    assert developer["marginal_area_sqft"] == 0


def test_tif_recapture_raises_the_authorization_and_restores_the_source(
    api: ApiClient,
) -> None:
    """A 50,000-cent recapture receipt lifts the authorization to 150,000 cents and the reserve floor to 7,500 cents, and the 54,000 cents now available clears that higher floor, so the source returns to ACTIVE and its parked packet returns to due diligence.

    A `CountyTreasurer` books a tax-increment recapture receipt by supplying `recapture_cents` and the `tax_year` it derives from; the amount is added both to `authorized_cents` and to the cumulative `recaptured_cents`, after which `available_cents`, `reserve_floor_cents` and `status` are all recomputed.

    Design: Corner/calculations/tif_recapture_raises_authorization_and_restores_source
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Recapture Line",
        source_type="TIF_RECAPTURE",
        authorized_cents=100000,
        restriction="ANY",
    )
    first_parcel = fixtures.create_property(
        api,
        address="2090 Cedar Ct",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    second_parcel = fixtures.create_property(
        api,
        address="2091 Cedar Ct",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )

    def _negotiated_packet(property_id: str, offer_price_cents: int) -> dict:
        payload = factories.without(
            factories.acquisition_packet_payload(
                property_id,
                funding_source["id"],
                channel="NEGOTIATED_PURCHASE",
                offer_price_cents=offer_price_cents,
                title_search_fee_cents=0,
            ),
            "donor_name",
        )
        return get_success_data(api.create_acquisition_packet(payload, INTAKE_1))

    big_packet = _negotiated_packet(first_parcel["id"], 96000)
    parked_packet = _negotiated_packet(second_parcel["id"], 1000)
    fixtures.board_approve_packet(api, big_packet["id"])

    # 100,000 - 96,000 = 4,000 available against a 5,000-cent floor, so the
    # source is CONSTRAINED and the untouched packet is parked.
    before = fixtures.read_funding_source(api, funding_source["id"])
    assert before["status"] == "CONSTRAINED"
    assert before["reserve_floor_cents"] == expected_reserve_floor_cents(100000)
    assert fixtures.read_packet(api, parked_packet["id"])["status"] == (
        "ON_HOLD_FUNDING"
    )

    source = validate_success(
        api.post_tif_recapture(
            funding_source["id"], {"recapture_cents": 50000, "tax_year": 2026}, TREAS_1
        )
    )

    assert source["authorized_cents"] == 150000
    assert source["recaptured_cents"] == 50000
    # 0.05 x 150,000 = 7,500, and 150,000 - 96,000 = 54,000 clears it.
    assert source["reserve_floor_cents"] == 7500
    assert source["status"] == "ACTIVE"
    assert_ledger_position(
        source,
        authorized_cents=150000,
        committed_cents=96000,
        disbursed_cents=0,
        available_cents=54000,
    )

    released = fixtures.read_packet(api, parked_packet["id"])
    assert released["status"] == "DUE_DILIGENCE"
    assert released["hold_reason"] is None


def test_order_estimate_is_swapped_for_the_actual_cost_on_completion(
    api: ApiClient,
) -> None:
    """Completing a 19,703-cent estimated mow for an invoiced 18,000 cents releases the whole estimate from committed money and disburses only the invoice, leaving 982,000 cents available.

    The funding source releases the estimate from `committed_cents` and adds the actual cost to `disbursed_cents` — the difference between estimate and invoice therefore returns to, or comes out of, `available_cents`

    Design: Corner/calculations/order_estimate_reconciles_to_actual_cost_on_completion
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Reconciliation Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
    )
    prop = fixtures.create_property(
        api,
        address="2120 Fir Ct",
        situs_ward=3,
        lot_area_sqft=10000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    fixtures.acquire_property(
        api, prop["id"], funding_source["id"], donor_name="Fir Court Estate"
    )
    contractor = fixtures.create_contractor(
        api,
        name="Reconciling Mowers",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )
    order = fixtures.schedule_order(
        api,
        prop["id"],
        funding_source_id=funding_source["id"],
        contractor_id=contractor["id"],
        work_type="MOW",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    assert order["estimated_cost_cents"] == 19703

    mid_flight = fixtures.read_funding_source(api, funding_source["id"])
    assert_ledger_position(
        mid_flight, committed_cents=19703, disbursed_cents=0, available_cents=980297
    )

    completed = validate_success(
        api.complete_maintenance_order(
            order["id"], {"actual_cost_cents": 18000}, INV_1
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["actual_cost_cents"] == 18000
    assert completed["estimated_cost_cents"] == 19703

    source = fixtures.read_funding_source(api, funding_source["id"])
    # 980,297 + 19,703 released - 18,000 spent = 982,000: the estimate comes back
    # in full and only the invoice leaves the source.
    assert_ledger_position(
        source,
        authorized_cents=1000000,
        committed_cents=0,
        disbursed_cents=18000,
        available_cents=982000,
    )

    mown = fixtures.read_property(api, prop["id"])
    assert_property(mown)
    assert mown["last_mow_at"] is not None
    assert mown["last_mow_at"].startswith("2026-08-01T00:00:00")
    assert mown["secured"] is False
