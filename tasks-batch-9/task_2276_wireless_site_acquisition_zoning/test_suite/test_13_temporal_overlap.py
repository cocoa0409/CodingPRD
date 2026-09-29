"""Two different interval semantics: half-open crew days and a symmetric hearing buffer."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import iso

FIRST_WINDOW_START = iso("2026-09-01")
FIRST_WINDOW_END = iso("2026-09-05")
ADJACENT_WINDOW_START = iso("2026-09-05")
ADJACENT_WINDOW_END = iso("2026-09-08")
OVERLAP_WINDOW_START = iso("2026-09-04")
OVERLAP_WINDOW_END = iso("2026-09-06")
FIRST_CREW_DAYS = 4
ADJACENT_CREW_DAYS = 3
LEDGER_AFTER_ADJACENT = 7

FIRST_HEARING_DATE = iso("2026-10-01")
TOO_CLOSE_HEARING_DATE = iso("2026-10-14")
EXACT_CADENCE_HEARING_DATE = iso("2026-10-15")


def _single_crew_provider_with_one_order(api: ApiClient) -> Dict[str, Any]:
    """A one-crew provider already booked over `[2026-09-01, 2026-09-05)`."""
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    provider = S.create_provider(
        api,
        name=C.SINGLE_CREW_PROVIDER_NAME,
        concurrent_crew_capacity=1,
        quoted_interval_days=20,
    )
    first = S.create_order(
        api,
        candidate["id"],
        provider["id"],
        "POWER",
        FIRST_WINDOW_START,
        FIRST_WINDOW_END,
    )
    chain.update(
        {"cand_id": candidate["id"], "prov_id": provider["id"], "first_id": first["id"]}
    )
    return chain


def test_an_order_starting_on_another_window_end_shares_no_day_and_is_accepted(
    api: ApiClient,
) -> None:
    """Half-open windows touch without overlapping, so one crew serves both.

    PRD: "Because the interval is half-open, an order whose `window_start` falls
    exactly on another order's `window_end` shares no day with it and never
    conflicts."

    PRD: "The order's `crew_days` is the whole UTC days spanned by that half-open
    window, discarding any partial day; a window that spans fewer than one whole day
    yields `ERR_INVALID_WINDOW` (422)."

    PRD: "The figure is recomputed after every order creation and after every status
    action, so it always equals that sum exactly."

    Design: Difficulty/resource_temporal_overlap/provider_half_open_crew_window_adjacent_allowed_overlap_rejected
    """
    chain = _single_crew_provider_with_one_order(api)

    first = ok(api.get_backhaul_order(chain["first_id"], headers=S.cm()))
    assert_fields(first, crew_days=FIRST_CREW_DAYS)

    adjacent = created(
        api.create_backhaul_order(
            {
                "candidate_id": chain["cand_id"],
                "provider_id": chain["prov_id"],
                "order_type": "FIBER",
                "window_start": ADJACENT_WINDOW_START,
                "window_end": ADJACENT_WINDOW_END,
            },
            headers=S.cm(),
        )
    )
    assert_fields(adjacent, crew_days=ADJACENT_CREW_DAYS, status="REQUESTED")

    provider = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(provider, committed_crew_days=LEDGER_AFTER_ADJACENT)


def test_a_window_covering_two_booked_days_is_refused_and_leaves_the_ledger_alone(
    api: ApiClient,
) -> None:
    """The day-by-day count exceeds one crew, so no third order exists.

    PRD: "For every UTC day covered by the new half-open window, the server counts the
    provider's existing orders in `REQUESTED` or `SCHEDULED` status whose own half-open
    window covers that day; adding one for the order being created, the result must not
    exceed the provider's `concurrent_crew_capacity` on any single day."

    PRD: "If it would, the order is refused with `ERR_PROVIDER_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/provider_half_open_crew_window_adjacent_allowed_overlap_rejected
    """
    chain = _single_crew_provider_with_one_order(api)
    S.create_order(
        api,
        chain["cand_id"],
        chain["prov_id"],
        "FIBER",
        ADJACENT_WINDOW_START,
        ADJACENT_WINDOW_END,
    )

    refused = api.create_backhaul_order(
        {
            "candidate_id": chain["cand_id"],
            "provider_id": chain["prov_id"],
            "order_type": "FIBER",
            "window_start": OVERLAP_WINDOW_START,
            "window_end": OVERLAP_WINDOW_END,
        },
        headers=S.cm(),
    )
    failed(refused, ApiError.PROVIDER_CAPACITY_EXCEEDED, expected_status=409)

    provider = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(provider, committed_crew_days=LEDGER_AFTER_ADJACENT)

    rows, meta = page(
        api.list_backhaul_orders({"provider_id": chain["prov_id"]}, headers=S.cm())
    )
    assert meta["total_count"] == 2, "the refused order was never created"
    assert len(rows) == 2, "only the two accepted orders are listed"


def _two_applications_one_hearing_booked(api: ApiClient) -> Dict[str, Any]:
    """Two `UNDER_REVIEW` filings in one jurisdiction, the first booked for 2026-10-01."""
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api, requires_visual_simulation=False)
    ring = S.create_open_ring(api)
    landlord = S.create_landlord(api)

    def _filing(**candidate_overrides: Any) -> str:
        candidate = S.create_candidate(
            api, ring["id"], landlord["id"], jurisdiction["id"], **candidate_overrides
        )
        S.engage_landlord(api, candidate["id"])
        lease = S.create_lease(api, candidate["id"], landlord["id"])
        S.accept_lease(api, lease["id"])
        S.execute_lease(api, lease["id"])
        application = S.create_zoning_application(api, candidate["id"])
        S.submit_zoning_application(api, application["id"])
        S.set_completeness(api, application["id"], "COMPLETE")
        return application["id"]

    za_one = _filing()
    za_two = _filing(
        site_type="ROOFTOP",
        lat=42.3540,
        lon=-71.0640,
        distance_from_center_m=260,
        agl_m=50,
        measured_rsrp_dbm=-90,
        offered_capacity_gbps=9,
    )
    S.hearing_action(api, za_one, "SCHEDULE", hearing_date=FIRST_HEARING_DATE)
    return {"za_one": za_one, "za_two": za_two}


def test_thirteen_days_of_separation_collides_with_the_booked_hearing(
    api: ApiClient,
) -> None:
    """The calendar buffer is symmetric around the booked point date and excludes 13 days.

    PRD: "And the jurisdiction's calendar must have room: no *other* zoning application
    in the same jurisdiction may hold a `hearing_date` strictly within the
    jurisdiction's `hearing_cadence_days` whole days of the requested date."

    PRD: "A separation exactly equal to `hearing_cadence_days` is allowed; anything
    closer yields `ERR_HEARING_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/jurisdiction_hearing_cadence_symmetric_buffer_around_point_date
    """
    scenario = _two_applications_one_hearing_booked(api)

    refused = api.hearing_action(
        scenario["za_two"],
        {"action": "SCHEDULE", "hearing_date": TOO_CLOSE_HEARING_DATE},
        headers=S.planner(),
    )
    failed(refused, ApiError.HEARING_WINDOW_CONFLICT, expected_status=409)

    second = ok(api.get_zoning_application(scenario["za_two"], headers=S.planner()))
    assert_fields(second, status="UNDER_REVIEW")
    assert second["hearing_date"] is None, "the rejected request booked nothing"


def test_exactly_the_cadence_of_separation_is_allowed(api: ApiClient) -> None:
    """Fourteen days is permitted, and the first application keeps its own date.

    PRD: "`SCHEDULE` books a hearing and is accepted from `UNDER_REVIEW` or from
    `HEARING_HELD`, storing the supplied `hearing_date` and moving the application to
    `HEARING_SCHEDULED`; it does not touch `continuance_count`."

    PRD: "The requested `hearing_date` must be at or after the current logical clock;
    an earlier date yields `ERR_HEARING_DATE_IN_PAST` (422)."

    Design: Difficulty/resource_temporal_overlap/jurisdiction_hearing_cadence_symmetric_buffer_around_point_date
    """
    scenario = _two_applications_one_hearing_booked(api)
    failed(
        api.hearing_action(
            scenario["za_two"],
            {"action": "SCHEDULE", "hearing_date": TOO_CLOSE_HEARING_DATE},
            headers=S.planner(),
        ),
        ApiError.HEARING_WINDOW_CONFLICT,
        expected_status=409,
    )

    booked = ok(
        api.hearing_action(
            scenario["za_two"],
            {"action": "SCHEDULE", "hearing_date": EXACT_CADENCE_HEARING_DATE},
            headers=S.planner(),
        )
    )
    assert_fields(booked, status="HEARING_SCHEDULED", continuance_count=0)
    assert_instant(booked["hearing_date"], EXACT_CADENCE_HEARING_DATE, "hearing_date")

    first = ok(api.get_zoning_application(scenario["za_one"], headers=S.planner()))
    assert_instant(first["hearing_date"], FIRST_HEARING_DATE, "hearing_date")
