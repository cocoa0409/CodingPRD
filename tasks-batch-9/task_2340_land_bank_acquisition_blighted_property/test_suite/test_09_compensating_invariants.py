"""
The authority's two conserved quantities and the pairs that compensate them.

Money is conserved on a funding source, where scheduling and cancelling a
maintenance order form an exact pair, and land is conserved across the whole
authority, where conveying a parcel and enforcing its reverter form the other.
Both are checked while the outbound half of the pair stands and again after the
inbound half has restored the position.
"""

from typing import Any, Dict

from test_helpers import (
    ApiClient,
    assert_development_agreement,
    assert_inventory_area_conserved,
    assert_ledger_identity,
    assert_ledger_position,
    assert_maintenance_order,
    assert_property,
    factories,
    fixtures,
    validate_success,
)
from test_helpers.test_users import CLERK_1, INV_1

# A 10,000 sqft mow is ten started thousand-square-foot blocks at 1,850 cents,
# an 18,500-cent subtotal, plus county overhead of 6.5 percent rounded half up.
MOW_ESTIMATE_10K_SQFT_CENTS = 19703
AUTHORIZED_CENTS = 1000000
# Five percent of the authorization, rounded half up.
RESERVE_FLOOR_CENTS = 50000

LOT_AREA_SQFT = 8500


def _parcel_with_scheduled_mow_order(api: ApiClient) -> Dict[str, Any]:
    """
    An unrestricted 1,000,000-cent line, one acquired 10,000 sqft parcel taken by
    donation with a zero title-search fee so nothing is disbursed, and one
    scheduled mowing order drawing on that line.
    """
    funding_source = fixtures.create_funding_source(api)
    prop = fixtures.create_property(
        api,
        address="190 Quarry Rd",
        situs_ward=5,
        lot_area_sqft=10000,
        assessed_value_cents=200000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=5,
    )
    fixtures.acquire_property(
        api,
        prop["id"],
        funding_source["id"],
        donor_name="Quarry Road Trust",
        title_search_fee_cents=0,
    )
    contractor = fixtures.create_contractor(
        api, name="Meadow Mowing Co", max_concurrent_crews=4, specialties=["MOW"]
    )
    order = fixtures.schedule_order(
        api,
        prop["id"],
        funding_source_id=funding_source["id"],
        contractor_id=contractor["id"],
        work_type="MOW",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
    )
    return {
        "funding_source": funding_source,
        "property": prop,
        "contractor": contractor,
        "order": order,
    }


def test_ledger_identity_holds_while_the_order_estimate_is_committed(
    api: ApiClient,
) -> None:
    """While a scheduled order's estimate sits in committed money, the authorized total still equals available plus committed plus disbursed to the cent.

    "The identity that authorized money always equals available plus committed plus disbursed money holds before and after every operation in this specification; each compensating pair — approve/decline, schedule/cancel, commit/disburse — restores it exactly."

    Design: Difficulty/compensating_invariant/funds_conserved_across_order_cancellation
    """
    bundle = _parcel_with_scheduled_mow_order(api)
    assert bundle["order"]["estimated_cost_cents"] == MOW_ESTIMATE_10K_SQFT_CENTS

    source = validate_success(
        api.get_funding_source(bundle["funding_source"]["id"], INV_1)
    )

    assert source["reserve_floor_cents"] == RESERVE_FLOOR_CENTS
    assert_ledger_position(
        source,
        authorized_cents=AUTHORIZED_CENTS,
        committed_cents=MOW_ESTIMATE_10K_SQFT_CENTS,
        disbursed_cents=0,
        available_cents=AUTHORIZED_CENTS - MOW_ESTIMATE_10K_SQFT_CENTS,
        status="ACTIVE",
    )
    assert_ledger_identity(source)


def test_cancelling_the_order_returns_the_whole_estimate_and_disburses_nothing(
    api: ApiClient,
) -> None:
    """Cancelling a scheduled order gives the full estimate back to available money without booking a single cent as disbursed, leaving the source exactly where it began.

    "Cancelling an order still in `SCHEDULED`, with a `cancelled_reason`, moves it `SCHEDULED → CANCELLED` and subtracts exactly `estimated_cost_cents` from the source's `committed_cents` with no disbursement whatsoever, after which `available_cents` is recomputed; if that release lifts the source back to at least its reserve floor, `CONSTRAINED → ACTIVE` fires and the parked packets return to `DUE_DILIGENCE`."

    Design: Difficulty/compensating_invariant/funds_conserved_across_order_cancellation
    """
    bundle = _parcel_with_scheduled_mow_order(api)
    funding_source_id = bundle["funding_source"]["id"]

    response = api.cancel_maintenance_order(
        bundle["order"]["id"],
        {"cancelled_reason": "Parcel scheduled for immediate side-lot transfer"},
        INV_1,
    )
    cancelled = validate_success(response, 200)

    assert_maintenance_order(cancelled)
    assert cancelled["status"] == "CANCELLED"
    # A cancellation settles nothing, so no invoiced cost is ever recorded.
    assert cancelled["actual_cost_cents"] is None
    assert cancelled["estimated_cost_cents"] == MOW_ESTIMATE_10K_SQFT_CENTS

    source = validate_success(api.get_funding_source(funding_source_id, INV_1))
    assert source["reserve_floor_cents"] == RESERVE_FLOOR_CENTS
    assert_ledger_position(
        source,
        authorized_cents=AUTHORIZED_CENTS,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=AUTHORIZED_CENTS,
        status="ACTIVE",
    )
    assert_ledger_identity(source)


def _board_approved_application_on_a_listed_parcel(api: ApiClient) -> Dict[str, Any]:
    """
    A single 8,500 sqft parcel driven to LISTED with clear title, and one
    developer application on it carried all the way to the board's approval. It
    is the only parcel in the system, so the authority-wide areas are
    unambiguous.
    """
    funding_source = fixtures.create_acquisition_funding_source(api)
    prop = fixtures.create_property(
        api,
        address="200 Rowan Pl",
        situs_ward=6,
        lot_area_sqft=LOT_AREA_SQFT,
        assessed_value_cents=1000000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=8,
    )
    fixtures.acquire_property(
        api,
        prop["id"],
        funding_source["id"],
        donor_name="Rowan Place Trust",
        title_search_fee_cents=20000,
    )
    fixtures.clear_title(api, prop["id"])
    fixtures.list_parcel(api, prop["id"])

    applicant = fixtures.create_developer_applicant(
        api,
        legal_name="Rowan Place Developers",
        contact_email="a@rowanplace.example",
    )
    application = fixtures.draft_application(
        api,
        prop["id"],
        applicant["id"],
        program="DEVELOPER_RFP",
        proposed_use="Nine-unit courtyard building",
        offer_price_cents=900000,
    )
    fixtures.submit_application(api, application["id"], applicant["id"])
    fixtures.screen_application(api, application["id"])
    fixtures.recommend_application(
        api, application["id"], "Sole responsive RFP offer."
    )
    fixtures.board_decide(api, application["id"], "APPROVE")
    return {
        "funding_source": funding_source,
        "property": prop,
        "applicant": applicant,
        "application": application,
    }


def test_conveyance_moves_the_whole_parcel_area_out_of_inventory(
    api: ApiClient,
) -> None:
    """A listed parcel counts wholly as inventory area, and executing its development agreement moves every one of its square feet into the conveyed area instead.

    "`inventory_area_sqft` is the sum of `lot_area_sqft` over every parcel whose `custody_status` is `ACQUIRED`, `LISTED` or `REVERTED`; `conveyed_area_sqft` is the same sum over parcels in `CONVEYED`; and `inventory_property_count` is the number of parcels in the three inventory states."

    Design: Difficulty/compensating_invariant/inventory_area_conserved_across_conveyance_and_reverter
    """
    bundle = _board_approved_application_on_a_listed_parcel(api)

    while_listed = validate_success(api.get_inventory_summary(INV_1))
    assert while_listed["inventory_area_sqft"] == LOT_AREA_SQFT
    assert while_listed["conveyed_area_sqft"] == 0
    assert while_listed["inventory_property_count"] == 1
    assert_inventory_area_conserved(while_listed, LOT_AREA_SQFT)

    response = api.create_development_agreement(
        factories.development_agreement_payload(
            bundle["application"]["id"],
            performance_deadline="2026-09-01T00:00:00Z",
            milestone_count=2,
            reverter_clause_active=True,
            abatement_years=3,
            discharge_mode="STATUTORY",
            projected_improved_value_cents=10000000,
        ),
        CLERK_1,
    )
    agreement = validate_success(response, 201)
    assert_development_agreement(agreement)
    assert agreement["status"] == "EXECUTED"

    after_conveyance = validate_success(api.get_inventory_summary(INV_1))
    assert after_conveyance["inventory_area_sqft"] == 0
    assert after_conveyance["conveyed_area_sqft"] == LOT_AREA_SQFT
    assert after_conveyance["inventory_property_count"] == 0
    assert_inventory_area_conserved(after_conveyance, LOT_AREA_SQFT)

    conveyed = fixtures.read_property(api, bundle["property"]["id"])
    assert_property(conveyed)
    assert conveyed["custody_status"] == "CONVEYED"
    assert conveyed["lot_area_sqft"] == LOT_AREA_SQFT


def test_reverter_returns_exactly_the_conveyed_area_to_inventory(
    api: ApiClient,
) -> None:
    """When the buyer reports no milestone and the cure period lapses, the reverter hands back precisely the square footage the conveyance took away.

    "Conveyance and reverter form an exact compensating pair on this quantity: executing a development agreement removes precisely the parcel's `lot_area_sqft` from the inventory area and adds it to the conveyed area, and enforcing the reverter returns precisely the same `lot_area_sqft`, so the inventory area after a reverter equals its value before the conveyance that preceded it."

    Design: Difficulty/compensating_invariant/inventory_area_conserved_across_conveyance_and_reverter
    """
    bundle = _board_approved_application_on_a_listed_parcel(api)
    agreement = fixtures.execute_agreement(
        api,
        bundle["application"]["id"],
        performance_deadline="2026-09-01T00:00:00Z",
        milestone_count=2,
        reverter_clause_active=True,
        abatement_years=3,
        discharge_mode="STATUTORY",
        projected_improved_value_cents=10000000,
    )
    after_conveyance = fixtures.inventory_summary(api)
    assert after_conveyance["inventory_area_sqft"] == 0
    assert after_conveyance["conveyed_area_sqft"] == LOT_AREA_SQFT

    # The performance deadline lapses with no milestone reported, so the first
    # sweep only opens the 90-day cure period.
    fixtures.set_clock(api, "2026-09-02T00:00:00Z")
    fixtures.run_compliance_sweep(api)

    # The cure deadline of 2026-11-30 is now behind the clock.
    fixtures.set_clock(api, "2026-12-01T00:00:00Z")
    sweep = validate_success(api.run_compliance_sweep(INV_1), 200)

    assert sweep["reverted_count"] == 1
    assert sweep["restored_inventory_sqft"] == LOT_AREA_SQFT

    after_reverter = validate_success(api.get_inventory_summary(INV_1))
    assert after_reverter["inventory_area_sqft"] == LOT_AREA_SQFT
    assert after_reverter["conveyed_area_sqft"] == 0
    assert after_reverter["inventory_property_count"] == 1
    assert_inventory_area_conserved(after_reverter, LOT_AREA_SQFT)

    reverted_agreement = fixtures.read_agreement(api, agreement["id"])
    assert_development_agreement(reverted_agreement)
    assert reverted_agreement["status"] == "REVERTED"

    reverted_parcel = fixtures.read_property(api, bundle["property"]["id"])
    assert_property(reverted_parcel)
    assert reverted_parcel["custody_status"] == "REVERTED"
    assert reverted_parcel["lot_area_sqft"] == LOT_AREA_SQFT
