"""
Rejections that come from a related record rather than from the target record.

In both cases the record the caller acts on is in a perfectly legal state: the
disposition application really is screened and the maintenance order really is
scheduled. What blocks the call lives on the parcel whose custody moved on, and
on the funding source the clock retired.
"""

from test_helpers import (
    DISP_1,
    DISP_2,
    INV_1,
    fixtures,
    validate_error,
)


# ── recommending against a parcel a rival buyer already took ────────────────
def _screened_runner_up_on_a_conveyed_parcel(api):
    """
    One listed parcel with two screened developer applications. The higher offer
    is recommended, board-approved and papered into an executed agreement, which
    conveys the parcel and leaves the runner-up resting in SCREENED.
    """
    bundle = fixtures.listed_parcel(
        api,
        funding_source=fixtures.create_acquisition_funding_source(api),
        property_overrides={
            "address": "150 Maple Row",
            "situs_ward": 2,
            "lot_area_sqft": 8500,
            "assessed_value_cents": 1000000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 8,
        },
        packet_overrides={
            "title_search_fee_cents": 20000,
            "donor_name": "Maple Row Trust",
        },
    )
    property_id = bundle["property"]["id"]

    runner_up = fixtures.create_developer_applicant(
        api, legal_name="Maple Row Builders", contact_email="b@maplerow.example"
    )
    runner_up_application = fixtures.draft_application(
        api,
        property_id,
        runner_up["id"],
        proposed_use="Eight-unit townhouse row",
        offer_price_cents=900000,
    )
    fixtures.submit_application(
        api, runner_up_application["id"], runner_up["id"]
    )
    runner_up_screening = fixtures.screen_application(
        api, runner_up_application["id"], DISP_1
    )

    winner = fixtures.create_developer_applicant(api)
    winning_application = fixtures.draft_application(
        api,
        property_id,
        winner["id"],
        proposed_use="Twelve-unit infill apartment building",
        offer_price_cents=950000,
    )
    fixtures.submit_application(api, winning_application["id"], winner["id"])
    fixtures.screen_application(api, winning_application["id"], DISP_1)
    fixtures.recommend_application(
        api, winning_application["id"], "Highest responsive RFP offer."
    )
    fixtures.board_decide(api, winning_application["id"], "APPROVE")
    agreement = fixtures.execute_agreement(api, winning_application["id"])

    return {
        "property_id": property_id,
        "runner_up_application_id": runner_up_application["id"],
        "runner_up_screening": runner_up_screening,
        "winning_application_id": winning_application["id"],
        "agreement": agreement,
    }


def test_recommendation_refused_once_the_parcel_has_been_conveyed(api):
    """
    A screened application cannot be recommended once the parcel it names has left the market for a rival buyer's deed.

    The parcel's `title_status` must still be `CLEAR` (`ERR_TITLE_NOT_CLEAR`) and its `custody_status` must still be `LISTED` (`ERR_PROPERTY_NOT_LISTED`).

    Design: Difficulty/cross_entity_state_dependency/recommend_blocked_by_conveyed_property_custody
    """
    scene = _screened_runner_up_on_a_conveyed_parcel(api)

    assert scene["runner_up_screening"]["outcome"] == "PASS"
    parcel = fixtures.read_property(api, scene["property_id"], DISP_1)
    assert parcel["custody_status"] == "CONVEYED"
    # Title stays clear through the conveyance, so the title guard cannot fire
    # and the custody guard is the only one left to answer.
    assert parcel["title_status"] == "CLEAR"

    response = api.recommend_application(
        scene["runner_up_application_id"],
        {"recommendation_memo": "Second-best responsive offer."},
        DISP_2,
    )

    validate_error(response, "ERR_PROPERTY_NOT_LISTED", 409)


def test_runner_up_application_is_untouched_by_the_custody_block(api):
    """
    The refused recommendation leaves the runner-up in SCREENED with no recommending officer recorded, while the rival's award stands.

    The parcel's `title_status` must still be `CLEAR` (`ERR_TITLE_NOT_CLEAR`) and its `custody_status` must still be `LISTED` (`ERR_PROPERTY_NOT_LISTED`).

    Design: Difficulty/cross_entity_state_dependency/recommend_blocked_by_conveyed_property_custody
    """
    scene = _screened_runner_up_on_a_conveyed_parcel(api)

    response = api.recommend_application(
        scene["runner_up_application_id"],
        {"recommendation_memo": "Second-best responsive offer."},
        DISP_2,
    )
    validate_error(response, "ERR_PROPERTY_NOT_LISTED", 409)

    runner_up = fixtures.read_application(api, scene["runner_up_application_id"])
    assert runner_up["status"] == "SCREENED"
    assert runner_up["recommended_by_user_id"] is None
    assert runner_up["recommendation_memo"] is None

    agreement = fixtures.read_agreement(api, scene["agreement"]["id"])
    assert agreement["status"] == "EXECUTED"
    winner = fixtures.read_application(api, scene["winning_application_id"])
    assert winner["status"] == "AWARDED"


# ── completing an order whose money the sweep has retired ───────────────────
def _scheduled_order_on_a_swept_funding_source(api):
    """
    A mowing order on an acquired parcel, funded from a grant that lapses on
    1 September 2026; the clock then moves past that instant and the compliance
    sweep retires the grant while the order is still scheduled.
    """
    acquisition_source = fixtures.create_acquisition_funding_source(api)
    maintenance_source = fixtures.create_funding_source(
        api,
        name="Lapsing Maintenance Grant",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
        expires_on="2026-09-01T00:00:00Z",
    )
    prop = fixtures.create_property(
        api,
        address="160 Nettle Ln",
        situs_ward=3,
        lot_area_sqft=10000,
        assessed_value_cents=200000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=5,
    )
    fixtures.acquire_property(
        api,
        prop["id"],
        acquisition_source["id"],
        title_search_fee_cents=10000,
        donor_name="Nettle Lane Trust",
    )
    contractor = fixtures.create_contractor(api)
    order = fixtures.schedule_order(
        api,
        prop["id"],
        funding_source_id=maintenance_source["id"],
        contractor_id=contractor["id"],
        work_type="MOW",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-07T00:00:00Z",
    )

    fixtures.set_clock(api, "2026-09-02T00:00:00Z")
    sweep = fixtures.run_compliance_sweep(api)

    return {
        "acquisition_source_id": acquisition_source["id"],
        "maintenance_source_id": maintenance_source["id"],
        "property_id": prop["id"],
        "order": order,
        "sweep": sweep,
    }


def test_completion_refused_when_the_sweep_has_expired_the_funding_source(api):
    """
    A scheduled order may not be completed once the compliance sweep has retired the funding source that backs it.

    An order whose funding source has been swept to `EXPIRED` can no longer be completed and is refused with `ERR_FUNDING_SOURCE_EXPIRED`.

    Design: Difficulty/cross_entity_state_dependency/order_completion_blocked_by_expired_funding_source
    """
    scene = _scheduled_order_on_a_swept_funding_source(api)

    # Ten thousand square feet mow at 18,500 cents of line item plus 1,203 cents
    # of county overhead.
    assert scene["order"]["estimated_cost_cents"] == 19703
    assert scene["order"]["status"] == "SCHEDULED"
    assert scene["sweep"]["funding_expired_count"] == 1

    lapsed = fixtures.read_funding_source(api, scene["maintenance_source_id"])
    assert lapsed["status"] == "EXPIRED"
    still_active = fixtures.read_funding_source(api, scene["acquisition_source_id"])
    assert still_active["status"] == "ACTIVE"

    response = api.complete_maintenance_order(
        scene["order"]["id"], {"actual_cost_cents": 19000}, INV_1
    )

    validate_error(response, "ERR_FUNDING_SOURCE_EXPIRED", 409)


def test_refused_completion_leaves_the_commitment_and_the_parcel_alone(api):
    """
    The refused completion converts nothing: the estimate stays committed on the expired source, the order stays scheduled and the mowing never lands.

    An order whose funding source has been swept to `EXPIRED` can no longer be completed and is refused with `ERR_FUNDING_SOURCE_EXPIRED`.

    Design: Difficulty/cross_entity_state_dependency/order_completion_blocked_by_expired_funding_source
    """
    scene = _scheduled_order_on_a_swept_funding_source(api)

    response = api.complete_maintenance_order(
        scene["order"]["id"], {"actual_cost_cents": 19000}, INV_1
    )
    validate_error(response, "ERR_FUNDING_SOURCE_EXPIRED", 409)

    order = fixtures.read_order(api, scene["order"]["id"])
    assert order["status"] == "SCHEDULED"
    assert order["actual_cost_cents"] is None
    assert order["completed_at"] is None

    ledger = fixtures.read_funding_source(api, scene["maintenance_source_id"])
    assert ledger["committed_cents"] == 19703
    assert ledger["disbursed_cents"] == 0
    assert ledger["available_cents"] == 980297

    parcel = fixtures.read_property(api, scene["property_id"])
    assert parcel["last_mow_at"] is None
