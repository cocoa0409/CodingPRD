"""Two contended resources under opposite interval conventions.

Laydown windows are half-open and share their zone's capacity in aggregate, so
overlap is legal until the summed pallets exceed the capacity and a window that
starts exactly when another ends does not overlap at all. Outage windows are
closed, exclusively occupied and padded by a two-hour switching buffer on both
sides, so a touching endpoint collides and a ninety-minute gap collides too.
"""

from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_OUTAGE_WINDOW_CONFLICT,
    ERR_YARD_WINDOW_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import assert_zone_occupancy
from test_helpers import factories as f
from test_helpers.fixtures import (
    answer_outage_window,
    create_project,
    create_substation,
    create_yard_zone,
    read_outage_window,
    read_substation,
    read_yard_zone,
    reserve_delivery,
    yard_zone_version,
)
from test_helpers.test_users import PROCUREMENT_COORDINATOR, UTILITY_COORDINATOR

# Each shipment is (component_type, unit_qty, pallets, arrival, window start, window end).
SHIPMENT_A = ("MODULE", 600, 60, "2026-08-03T09:00:00Z", "2026-08-03T00:00:00Z", "2026-08-07T00:00:00Z")
SHIPMENT_B = ("TRACKER", 500, 50, "2026-08-05T09:00:00Z", "2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z")
SHIPMENT_C = ("TRACKER", 300, 30, "2026-08-07T09:00:00Z", "2026-08-07T00:00:00Z", "2026-08-09T00:00:00Z")
SHIPMENT_D = ("INVERTER", 20, 10, "2026-08-06T09:00:00Z", "2026-08-06T00:00:00Z", "2026-08-08T00:00:00Z")
SHIPMENT_E = ("INVERTER", 2, 1, "2026-08-06T10:00:00Z", "2026-08-06T00:00:00Z", "2026-08-08T00:00:00Z")


def _spec(shipment):
    """Turn one shipment tuple into delivery payload fields."""
    component_type, unit_qty, pallets, arrival, start, end = shipment
    return {
        "component_type": component_type,
        "unit_qty": unit_qty,
        "pallets": pallets,
        "planned_arrival_at": arrival,
        "laydown_window_start": start,
        "laydown_window_end": end,
    }


def _hundred_pallet_zone(api):
    """An empty hundred-position zone already holding the first sixty pallets."""
    project = create_project(api, name="Creosote Mesa")
    zone = create_yard_zone(api, project["id"], zone_code="Y1", pallet_capacity=100)
    first = reserve_delivery(api, project["id"], zone["id"], **_spec(SHIPMENT_A))
    return project, zone, first


def _attempt(api, project_id, zone_id, shipment, expected_version):
    """Request pallet positions without asserting the outcome."""
    payload = f.delivery_payload(
        project_id, zone_id, expected_version, **_spec(shipment)
    )
    return api.create_delivery(payload, PROCUREMENT_COORDINATOR)


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/laydown_yard_half_open_windows_share_capacity_in_aggregate
# ---------------------------------------------------------------------------
def test_an_overlapping_shipment_is_refused_on_the_summed_pallets(api):
    """Sixty reserved plus fifty requested is a hundred and ten in a zone of a hundred.

    PRD 3.3: "The `pallets` of the overlapping set are summed, the candidate's own
    `pallets` are added, and if that total exceeds the zone's `pallet_capacity` the
    reservation is refused with `ERR_YARD_WINDOW_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/laydown_yard_half_open_windows_share_capacity_in_aggregate
    """
    project, zone, _first = _hundred_pallet_zone(api)
    version = yard_zone_version(api, zone["id"])

    response = _attempt(api, project["id"], zone["id"], SHIPMENT_B, version)

    validate_error(response, ERR_YARD_WINDOW_CAPACITY_EXCEEDED, expected_status=409)


def test_a_window_that_merely_abuts_another_does_not_overlap_it(api):
    """A shipment starting exactly when the first ends sees an empty zone.

    PRD 3.3: "Shipments that merely abut the candidate, ending exactly when it
    begins, are not overlapping and are ignored."

    Design: Difficulty/resource_temporal_overlap/laydown_yard_half_open_windows_share_capacity_in_aggregate
    """
    project, zone, _first = _hundred_pallet_zone(api)
    version = yard_zone_version(api, zone["id"])

    response = _attempt(api, project["id"], zone["id"], SHIPMENT_C, version)

    touching = validate_success(response, expected_status=201)
    assert touching["status"] == "RESERVED"


def test_a_shipment_overlapping_two_others_is_admitted_exactly_at_capacity(api):
    """Sixty plus thirty plus ten is a hundred, which is at the capacity, not over it.

    PRD 3.3: "The system collects every other delivery in the same zone whose
    `status` is `RESERVED`, `ARRIVED` or `ACCEPTED` and whose window genuinely
    overlaps the candidate's — that is, whose `laydown_window_start` is strictly
    earlier than the candidate's `laydown_window_end` and whose
    `laydown_window_end` is strictly later than the candidate's
    `laydown_window_start`."

    Design: Difficulty/resource_temporal_overlap/laydown_yard_half_open_windows_share_capacity_in_aggregate
    """
    project, zone, _first = _hundred_pallet_zone(api)
    _attempt(api, project["id"], zone["id"], SHIPMENT_B, yard_zone_version(api, zone["id"]))
    _attempt(api, project["id"], zone["id"], SHIPMENT_C, yard_zone_version(api, zone["id"]))

    response = _attempt(
        api, project["id"], zone["id"], SHIPMENT_D, yard_zone_version(api, zone["id"])
    )

    at_capacity = validate_success(response, expected_status=201)
    assert at_capacity["status"] == "RESERVED"
    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=100, available_pallets=0
    )


def test_one_pallet_past_capacity_is_refused(api):
    """A single further pallet over the same window would make a hundred and one.

    PRD 3.3: "This pairwise-overlap sum against the candidate is the pinned
    definition of occupancy: there is no interval splitting and no scan for a peak
    profile across sub-intervals."

    Design: Difficulty/resource_temporal_overlap/laydown_yard_half_open_windows_share_capacity_in_aggregate
    """
    project, zone, _first = _hundred_pallet_zone(api)
    _attempt(api, project["id"], zone["id"], SHIPMENT_C, yard_zone_version(api, zone["id"]))
    _attempt(api, project["id"], zone["id"], SHIPMENT_D, yard_zone_version(api, zone["id"]))

    response = _attempt(
        api, project["id"], zone["id"], SHIPMENT_E, yard_zone_version(api, zone["id"])
    )

    validate_error(response, ERR_YARD_WINDOW_CAPACITY_EXCEEDED, expected_status=409)


def test_only_the_admitted_reservations_moved_the_zone_version(api):
    """Three accepted reservations bump the version three times; two refusals do not.

    PRD 3.3: "When the check passes, the delivery is persisted with `status`
    `RESERVED`, its `received_unit_qty`, `damaged_unit_qty`, `accepted_unit_qty`,
    `damage_ratio` and `cancel_reason` all null, and the zone's `reserved_pallets`
    and `available_pallets` are recomputed with the zone's `version` incremented by
    1."

    Design: Difficulty/resource_temporal_overlap/laydown_yard_half_open_windows_share_capacity_in_aggregate
    """
    project, zone, _first = _hundred_pallet_zone(api)
    after_a = yard_zone_version(api, zone["id"])

    _attempt(api, project["id"], zone["id"], SHIPMENT_B, after_a)
    assert yard_zone_version(api, zone["id"]) == after_a

    _attempt(api, project["id"], zone["id"], SHIPMENT_C, after_a)
    after_c = yard_zone_version(api, zone["id"])
    _attempt(api, project["id"], zone["id"], SHIPMENT_D, after_c)
    after_d = yard_zone_version(api, zone["id"])

    assert after_a < after_c < after_d
    _attempt(api, project["id"], zone["id"], SHIPMENT_E, after_d)
    assert yard_zone_version(api, zone["id"]) == after_d
    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=100, available_pallets=0
    )


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/outage_windows_are_exclusive_with_a_switching_buffer
# ---------------------------------------------------------------------------
APPROVED_OUTAGE = ("2026-08-10T00:00:00Z", "2026-08-10T04:00:00Z", "BACKFEED")
NINETY_MINUTE_GAP = ("2026-08-10T05:30:00Z", "2026-08-10T07:00:00Z", "SWITCHING")
TOUCHING_ENDPOINT = ("2026-08-10T04:00:00Z", "2026-08-10T05:00:00Z", "SWITCHING")
PAST_THE_BUFFER = ("2026-08-10T06:01:00Z", "2026-08-10T08:00:00Z", "TIE_IN")


def _feeder_with_one_approved_outage(api):
    """A brand-new substation whose only window is an approved four-hour backfeed."""
    project = create_project(api, name="Saguaro Gap")
    substation = create_substation(
        api,
        project["id"],
        substation_code="S1",
        interconnection_voltage_kv=138.0,
        mv_collection_km=12.5,
    )
    first = _ask(api, substation["id"], APPROVED_OUTAGE)
    approved = validate_success(first, expected_status=201)
    answer_outage_window(api, approved["id"], "APPROVE", utility_reference="SO-4471")
    return project, substation, approved


def _ask(api, substation_id, window):
    """Request a switching outage without asserting the outcome."""
    start_at, end_at, purpose = window
    return api.create_outage_window(
        substation_id,
        f.outage_window_payload(start_at=start_at, end_at=end_at, purpose=purpose),
        UTILITY_COORDINATOR,
    )


def test_a_ninety_minute_gap_is_still_inside_the_switching_buffer(api):
    """05:30 is within two hours of the 04:00 end, so the feeder is not free yet.

    PRD 3.6: "Because the intervals are closed and both sides are padded, two
    windows that merely touch collide, and so do two windows separated by a gap of
    120 minutes or less; a gap strictly greater than 120 minutes clears."

    Design: Difficulty/resource_temporal_overlap/outage_windows_are_exclusive_with_a_switching_buffer
    """
    _project, substation, _approved = _feeder_with_one_approved_outage(api)

    response = _ask(api, substation["id"], NINETY_MINUTE_GAP)

    validate_error(response, ERR_OUTAGE_WINDOW_CONFLICT, expected_status=409)


def test_a_touching_endpoint_collides_because_the_intervals_are_closed(api):
    """Starting at the exact instant the approved window ends is a collision here.

    PRD 3.6: "The candidate collides with such a window when the candidate's
    `start_at` is at or before that window's `end_at` advanced by the two-hour
    switching buffer of 120 minutes, and simultaneously the candidate's `end_at`
    advanced by the same 120-minute buffer is at or after that window's
    `start_at`."

    Design: Difficulty/resource_temporal_overlap/outage_windows_are_exclusive_with_a_switching_buffer
    """
    _project, substation, _approved = _feeder_with_one_approved_outage(api)

    response = _ask(api, substation["id"], TOUCHING_ENDPOINT)

    validate_error(response, ERR_OUTAGE_WINDOW_CONFLICT, expected_status=409)


def test_one_minute_past_the_buffer_clears_the_feeder(api):
    """06:01 is a minute beyond 04:00 plus two hours, and the request is granted.

    PRD 3.6: "The request is persisted at `REQUESTED` with `utility_reference` and
    `responded_at` null, and it bumps no parent version."

    Design: Difficulty/resource_temporal_overlap/outage_windows_are_exclusive_with_a_switching_buffer
    """
    _project, substation, _approved = _feeder_with_one_approved_outage(api)

    response = _ask(api, substation["id"], PAST_THE_BUFFER)

    granted = validate_success(response, expected_status=201)
    assert granted["status"] == "REQUESTED"
    assert granted["utility_reference"] is None
    assert granted["responded_at"] is None


def test_denying_a_window_frees_the_feeder_for_an_identical_re_request(api):
    """The same bounds that were just granted can be granted again once denied.

    PRD 3.6: "`DENY` drives `REQUESTED → DENIED`, which is terminal and which
    additionally frees the feeder: from that moment the window is excluded from
    the conflict comparison, so a request that had been blocked by it can be
    resubmitted and accepted."

    Design: Difficulty/resource_temporal_overlap/outage_windows_are_exclusive_with_a_switching_buffer
    """
    _project, substation, _approved = _feeder_with_one_approved_outage(api)
    second = validate_success(_ask(api, substation["id"], PAST_THE_BUFFER), expected_status=201)

    denied = answer_outage_window(api, second["id"], "DENY", utility_reference="SO-4472")
    assert denied["status"] == "DENIED"

    third = validate_success(_ask(api, substation["id"], PAST_THE_BUFFER), expected_status=201)

    assert third["status"] == "REQUESTED"
    assert third["id"] != second["id"]


def test_the_feeder_keeps_every_window_it_was_ever_asked_for_and_stays_unbuilt(api):
    """Three windows survive as APPROVED, DENIED and REQUESTED; the facility has not moved.

    PRD 3.6: "Every other window on the same facility whose `status` is
    `REQUESTED`, `APPROVED` or `EXECUTED` is examined; windows that were `DENIED`
    have released the feeder and are excluded from the comparison entirely."

    Design: Difficulty/resource_temporal_overlap/outage_windows_are_exclusive_with_a_switching_buffer
    """
    _project, substation, approved = _feeder_with_one_approved_outage(api)
    _ask(api, substation["id"], NINETY_MINUTE_GAP)
    _ask(api, substation["id"], TOUCHING_ENDPOINT)
    second = validate_success(_ask(api, substation["id"], PAST_THE_BUFFER), expected_status=201)
    answer_outage_window(api, second["id"], "DENY", utility_reference="SO-4472")
    third = validate_success(_ask(api, substation["id"], PAST_THE_BUFFER), expected_status=201)

    windows, meta = validate_paginated(
        api.list_substation_outage_windows(substation["id"], UTILITY_COORDINATOR)
    )

    assert meta["total_count"] == 3
    by_id = {window["id"]: window["status"] for window in windows}
    assert by_id == {
        approved["id"]: "APPROVED",
        second["id"]: "DENIED",
        third["id"]: "REQUESTED",
    }
    assert read_outage_window(api, second["id"])["status"] == "DENIED"
    assert read_substation(api, substation["id"])["status"] == "SITE_CIVIL"
