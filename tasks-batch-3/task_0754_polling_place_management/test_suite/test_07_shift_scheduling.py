"""Shift scheduling constraints: validity, per-worker overlap, place station capacity.

Queue A (difficulty): resource_temporal_overlap. Queue B: shift end-before-start.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_election, create_place, create_certified_worker, create_active_assignment,
    create_shift_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]


def _worker_with_active_assignment(api, *, place_id, full_name, email):
    w = create_certified_worker(api, full_name=full_name, email=email)
    a = create_active_assignment(api, worker_id=w["id"], place_id=place_id)
    return w, a


# ---- validations / error_shift_end_before_start ----

def test_shift_end_not_after_start_is_invalid_request(api):
    """PRD §3.5: "The `scheduled_end` must be strictly after `scheduled_start`; otherwise the
    request is rejected with `ERR_INVALID_REQUEST` (422)."

    Design: Corner/validations/error_shift_end_before_start_returns_invalid_request
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"])
    _, a = _worker_with_active_assignment(api, place_id=pp["id"], full_name="W1", email="w1@x.com")
    resp = api.create_shift(
        create_shift_payload(a["id"], "2026-11-03T12:00:00Z", "2026-11-03T09:00:00Z"), CAPTAIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---- resource_temporal_overlap / worker_shift_pairwise_overlap_half_open ----

def test_same_worker_overlapping_shift_rejected(api):
    """PRD §3.5: "the new shift's half-open window `[scheduled_start, scheduled_end)` must not
    overlap any other shift of the same worker; two shifts that merely touch at a shared
    boundary do not overlap and are allowed. A violation is `ERR_WORKER_SHIFT_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/worker_shift_pairwise_overlap_half_open
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"])
    _, a = _worker_with_active_assignment(api, place_id=pp["id"], full_name="Jane", email="jane@x.com")
    get_success_data(api.create_shift(
        create_shift_payload(a["id"], "2026-11-03T09:00:00Z", "2026-11-03T12:00:00Z"), CAPTAIN))
    resp = api.create_shift(
        create_shift_payload(a["id"], "2026-11-03T11:00:00Z", "2026-11-03T13:00:00Z"), CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_WORKER_SHIFT_OVERLAP)


def test_same_worker_adjacent_shift_allowed(api):
    """PRD §3.5: "the new shift's half-open window `[scheduled_start, scheduled_end)` must not
    overlap any other shift of the same worker; two shifts that merely touch at a shared
    boundary do not overlap and are allowed. A violation is `ERR_WORKER_SHIFT_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/worker_shift_pairwise_overlap_half_open
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"])
    _, a = _worker_with_active_assignment(api, place_id=pp["id"], full_name="Jane", email="jane@x.com")
    get_success_data(api.create_shift(
        create_shift_payload(a["id"], "2026-11-03T09:00:00Z", "2026-11-03T12:00:00Z"), CAPTAIN))
    resp = api.create_shift(
        create_shift_payload(a["id"], "2026-11-03T12:00:00Z", "2026-11-03T14:00:00Z"), CAPTAIN)
    validate_success(resp, 201)


# ---- resource_temporal_overlap / place_station_aggregate_capacity_overlap ----

def test_place_station_capacity_exceeded_by_overlap(api):
    """PRD §3.5: "the number of existing shifts at the place whose windows overlap the new
    shift's window must be strictly less than the place's `station_capacity`; if admitting the
    new shift would meet or exceed capacity, it is rejected with `ERR_PLACE_CAPACITY_EXCEEDED`
    (409)."

    Design: Difficulty/resource_temporal_overlap/place_station_aggregate_capacity_overlap
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"], staffing_capacity=5, station_capacity=1)
    _, aa = _worker_with_active_assignment(api, place_id=pp["id"], full_name="W A", email="a@x.com")
    _, ab = _worker_with_active_assignment(api, place_id=pp["id"], full_name="W B", email="b@x.com")
    get_success_data(api.create_shift(
        create_shift_payload(aa["id"], "2026-11-03T09:00:00Z", "2026-11-03T12:00:00Z"), CAPTAIN))
    resp = api.create_shift(
        create_shift_payload(ab["id"], "2026-11-03T11:00:00Z", "2026-11-03T13:00:00Z"), CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_PLACE_CAPACITY_EXCEEDED)


def test_place_station_capacity_allows_non_overlapping_shift(api):
    """PRD §3.5: "the number of existing shifts at the place whose windows overlap the new
    shift's window must be strictly less than the place's `station_capacity`; if admitting the
    new shift would meet or exceed capacity, it is rejected with `ERR_PLACE_CAPACITY_EXCEEDED`
    (409)."

    Design: Difficulty/resource_temporal_overlap/place_station_aggregate_capacity_overlap
    """
    el = create_election(api)
    pp = create_place(api, election_id=el["id"], staffing_capacity=5, station_capacity=1)
    _, aa = _worker_with_active_assignment(api, place_id=pp["id"], full_name="W A", email="a@x.com")
    _, ab = _worker_with_active_assignment(api, place_id=pp["id"], full_name="W B", email="b@x.com")
    get_success_data(api.create_shift(
        create_shift_payload(aa["id"], "2026-11-03T09:00:00Z", "2026-11-03T12:00:00Z"), CAPTAIN))
    # Non-overlapping (adjacent at the shared 12:00 boundary): zero overlapping existing shifts
    # < station_capacity 1, so it is admitted.
    resp = api.create_shift(
        create_shift_payload(ab["id"], "2026-11-03T12:00:00Z", "2026-11-03T14:00:00Z"), CAPTAIN)
    validate_success(resp, 201)
