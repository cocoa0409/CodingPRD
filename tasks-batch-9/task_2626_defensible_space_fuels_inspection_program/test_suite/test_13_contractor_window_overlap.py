"""The contractor's closed work window: touching endpoints do conflict."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_CONTRACTOR_WINDOW_CONFLICT,
    add_zones,
    advance_cycle,
    assert_hours,
    authorize_abatement,
    award_order,
    award_payload,
    complete_inspection,
    create_contractor,
    create_inspector,
    create_parcel,
    get_contractor,
    get_order,
    notice_for_parcel,
    open_cycle,
    schedule_inspection,
    serve_notice,
    set_clock,
)
from test_helpers.test_users import FIRE_MARSHAL_HEADERS

VISIT_WINDOWS = (
    ("2026-08-20T15:00:00Z", "2026-08-20T17:00:00Z"),
    ("2026-08-21T15:00:00Z", "2026-08-21T17:00:00Z"),
    ("2026-08-22T15:00:00Z", "2026-08-22T17:00:00Z"),
)


def _three_authorized_orders(client):
    """Three overdue citations escalated into AUTHORIZED orders, two of them awarded.

    One contractor with a daily ceiling of 3 holds 2026-10-05T08:00Z-18:00Z on the
    first order and 2026-10-06T08:00Z-18:00Z on the second, 12.5 crew hours each,
    so 25.0 hours stand committed and the third order is still unawarded.
    """
    cycle = open_cycle(client, notice_lead_days=10)
    inspector = create_inspector(client)
    parcels = [create_parcel(client) for _ in range(3)]
    inspections = []
    for parcel, (start, end) in zip(parcels, VISIT_WINDOWS):
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc=start,
            scheduled_end_utc=end,
        )
        serve_notice(client, inspection["id"])
        add_zones(client, inspection["id"], inspector["id"])
        inspections.append(inspection)

    set_clock(client, "2026-08-23T00:00:00Z")
    for inspection in inspections:
        complete_inspection(client, inspection["id"], inspector["id"], "FAIL")

    set_clock(client, "2026-10-01T00:00:00Z")
    advance_cycle(client, cycle["id"])

    contractor = create_contractor(client, max_daily_orders=3)
    orders = []
    for parcel in parcels:
        notice = notice_for_parcel(client, parcel["id"])
        assert notice["status"] == "OVERDUE"
        orders.append(authorize_abatement(client, notice["id"]))

    orders[0] = award_order(
        client,
        orders[0]["id"],
        contractor["id"],
        12.5,
        "2026-10-05T08:00:00Z",
        "2026-10-05T18:00:00Z",
    )
    orders[1] = award_order(
        client,
        orders[1]["id"],
        contractor["id"],
        12.5,
        "2026-10-06T08:00:00Z",
        "2026-10-06T18:00:00Z",
    )
    return {"cycle": cycle, "contractor": contractor, "orders": orders}


class TestContractorWindowOverlap:
    """Unlike the inspector rule, an award starting when another job ends conflicts."""

    def test_a_start_equal_to_an_existing_end_is_refused_and_reserves_nothing(
        self, client
    ):
        """2026-10-05T18:00Z is inside the first job's closed window, so the award
        is refused; one second later it is accepted.

        PRD: "The work window is treated as closed - it occupies every instant
        from work_start_utc through work_end_utc inclusive - and it must not
        intersect the closed window of any other order of the same contractor
        standing in AWARDED or WORK_COMPLETE; unlike the inspector rule, touching
        endpoints do conflict here, so a new job starting at the exact instant an
        existing job ends is refused with ERR_CONTRACTOR_WINDOW_CONFLICT."

        PRD: "A successful award stores contractor_id, crew_hours, work_start_utc
        and work_end_utc, moves the order AUTHORIZED -> AWARDED, and increases the
        contractor's committed_crew_hours by the reserved crew_hours."

        PRD: "This is an aggregate-per-day test, not a pairwise one: with the
        default cap of 2, a third overlapping job on the same Tuesday is refused
        even though no two of the three windows are identical."

        Design: Difficulty/resource_temporal_overlap/contractor_closed_window_touching_endpoint_conflict
        """
        world = _three_authorized_orders(client)
        contractor_id = world["contractor"]["id"]
        third = world["orders"][2]
        assert_hours(
            get_contractor(client, contractor_id)["committed_crew_hours"], 25.0
        )

        validate_error(
            client.award_order(
                third["id"],
                award_payload(
                    contractor_id, 12.5, "2026-10-05T18:00:00Z", "2026-10-05T20:00:00Z"
                ),
                headers=FIRE_MARSHAL_HEADERS,
            ),
            ERR_CONTRACTOR_WINDOW_CONFLICT,
        )
        refused = get_order(client, third["id"])
        assert refused["status"] == "AUTHORIZED"
        assert refused["contractor_id"] is None
        assert_hours(
            get_contractor(client, contractor_id)["committed_crew_hours"], 25.0
        )

        # One second clear of the endpoint, and only two jobs on 2026-10-05
        # against a ceiling of 3, so the daily rule cannot be what fired above.
        awarded = award_order(
            client,
            third["id"],
            contractor_id,
            12.5,
            "2026-10-05T18:00:01Z",
            "2026-10-05T20:00:00Z",
        )
        assert awarded["status"] == "AWARDED"
        assert_hours(
            get_contractor(client, contractor_id)["committed_crew_hours"], 37.5
        )

    def test_an_end_equal_to_an_existing_start_is_refused_but_not_for_a_second_crew(
        self, client
    ):
        """Both endpoints are closed, so a window ending at another job's start is
        refused too - though only for the contractor that already holds it.

        PRD: "The work window is treated as closed - it occupies every instant
        from work_start_utc through work_end_utc inclusive - and it must not
        intersect the closed window of any other order of the same contractor
        standing in AWARDED or WORK_COMPLETE; unlike the inspector rule, touching
        endpoints do conflict here, so a new job starting at the exact instant an
        existing job ends is refused with ERR_CONTRACTOR_WINDOW_CONFLICT."

        PRD: "Contractor occupation conflict - the new closed work window must not
        intersect another live awarded window of the same contractor."

        Design: Difficulty/resource_temporal_overlap/contractor_closed_window_touching_endpoint_conflict
        """
        world = _three_authorized_orders(client)
        contractor_id = world["contractor"]["id"]
        third = world["orders"][2]

        validate_error(
            client.award_order(
                third["id"],
                award_payload(
                    contractor_id, 12.5, "2026-10-05T06:00:00Z", "2026-10-05T08:00:00Z"
                ),
                headers=FIRE_MARSHAL_HEADERS,
            ),
            ERR_CONTRACTOR_WINDOW_CONFLICT,
        )
        assert_hours(
            get_contractor(client, contractor_id)["committed_crew_hours"], 25.0
        )

        other = create_contractor(client)
        awarded = award_order(
            client,
            third["id"],
            other["id"],
            12.5,
            "2026-10-05T18:00:00Z",
            "2026-10-05T20:00:00Z",
        )
        assert awarded["status"] == "AWARDED"
        assert awarded["contractor_id"] == other["id"]
        assert_hours(get_contractor(client, other["id"])["committed_crew_hours"], 12.5)
        assert_hours(
            get_contractor(client, contractor_id)["committed_crew_hours"], 25.0
        )
