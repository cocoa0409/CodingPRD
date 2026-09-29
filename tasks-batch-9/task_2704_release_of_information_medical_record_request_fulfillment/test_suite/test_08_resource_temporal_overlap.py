"""Two contended resources: a patient's coverage windows and a facility's legacy gateway."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ANALYST_1, INTAKE_1
from test_helpers.assertions import Instant


# --------------------------------------------------------------------------
# authorization_coverage_half_open_allows_adjacency
# --------------------------------------------------------------------------
def _patient_holding_window_a(api):
    """One incumbent authorization covering GENERAL_MEDICAL over [2026-08-01, 2026-09-01)."""
    world = fx.base_world(api)
    attorney = fx.make_attorney(api)
    window_a = fx.make_authorization(
        api,
        world["patient_id"],
        attorney["id"],
        signed_at="2026-08-01T00:00:00Z",
        expires_at="2026-09-01T00:00:00Z",
    )
    return {"world": world, "requester_id": attorney["id"], "window_a": window_a["id"]}


def _propose_window(api, scenario, signed_at, expires_at, scope=None, **extra):
    """Attempt one more coverage window on the same patient and requesting party."""
    payload = f.authorization_payload(
        scenario["world"]["patient_id"],
        scenario["requester_id"],
        fx.patient_version(api, scenario["world"]["patient_id"]),
        scope_categories=scope or ["GENERAL_MEDICAL"],
        signed_at=signed_at,
        expires_at=expires_at,
        **extra,
    )
    return api.create_authorization(payload, INTAKE_1)


def _read_authorization(api, authorization_id):
    return get_success_data(api.get_authorization(authorization_id, INTAKE_1))


def test_a_window_intersecting_the_incumbent_on_time_and_scope_is_refused(api):
    """[2026-08-15, 2026-10-01) collides with [2026-08-01, 2026-09-01) on GENERAL_MEDICAL.

    PRD: "Before accepting a new authorization the system looks for an existing authorization on the same `patient_id` and the same `requester_id` whose `status` is `VALID` or `DEFECTIVE`, whose `id` is not the one named by `supersedes_authorization_id`, and whose `scope_categories` share at least one member with the new one's; if any such incumbent's coverage interval — half-open, beginning at its `signed_at` and running up to but not including its `expires_at` — overlaps the new one's interval on the same half-open reading, the creation is refused with `ERR_AUTHORIZATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/authorization_coverage_half_open_allows_adjacency
    """
    scenario = _patient_holding_window_a(api)
    patient_id = scenario["world"]["patient_id"]
    version_before = fx.patient_version(api, patient_id)

    response = _propose_window(api, scenario, "2026-08-15T00:00:00Z", "2026-10-01T00:00:00Z")
    validate_error(response, e.ERR_AUTHORIZATION_WINDOW_OVERLAP, 409)

    assert _read_authorization(api, scenario["window_a"])["status"] == "VALID"
    assert fx.patient_version(api, patient_id) == version_before


def test_a_window_starting_at_the_incumbents_expiry_is_adjacent_not_overlapping(api):
    """The upper bound is exclusive, so 2026-09-01 is free the instant A ends.

    PRD: "Because the interval is half-open, a new authorization whose `signed_at` is exactly the incumbent's `expires_at` is adjacent rather than overlapping and is accepted."

    Design: Difficulty/resource_temporal_overlap/authorization_coverage_half_open_allows_adjacency
    """
    scenario = _patient_holding_window_a(api)

    window_c = validate_success(
        _propose_window(api, scenario, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"), 201
    )

    assert window_c["status"] == "VALID"
    assert _read_authorization(api, scenario["window_a"])["status"] == "VALID"


def test_windows_that_share_no_record_category_may_overlap_freely(api):
    """Collision needs both axes; a BEHAVIORAL_HEALTH window ignores the incumbent's time.

    PRD: "Before accepting a new authorization the system looks for an existing authorization on the same `patient_id` and the same `requester_id` whose `status` is `VALID` or `DEFECTIVE`, whose `id` is not the one named by `supersedes_authorization_id`, and whose `scope_categories` share at least one member with the new one's; if any such incumbent's coverage interval — half-open, beginning at its `signed_at` and running up to but not including its `expires_at` — overlaps the new one's interval on the same half-open reading, the creation is refused with `ERR_AUTHORIZATION_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/authorization_coverage_half_open_allows_adjacency
    """
    scenario = _patient_holding_window_a(api)

    window_d = validate_success(
        _propose_window(
            api,
            scenario,
            "2026-08-15T00:00:00Z",
            "2026-10-01T00:00:00Z",
            scope=["BEHAVIORAL_HEALTH"],
        ),
        201,
    )

    assert window_d["status"] == "VALID"
    assert window_d["scope_categories"] == ["BEHAVIORAL_HEALTH"]


def test_naming_the_incumbent_exempts_a_strictly_contained_window(api):
    """[2026-08-20, 2026-08-25) sits wholly inside A, and supersession admits it.

    PRD: "When `supersedes_authorization_id` is present and names an authorization whose `patient_id` equals the new authorization's `patient_id`, the named predecessor is driven from `VALID` or `DEFECTIVE` to `SUPERSEDED` and its `version` increments by 1; the successor is exempt from the overlap check above."

    Design: Difficulty/resource_temporal_overlap/authorization_coverage_half_open_allows_adjacency
    """
    scenario = _patient_holding_window_a(api)

    window_e = validate_success(
        _propose_window(
            api,
            scenario,
            "2026-08-20T00:00:00Z",
            "2026-08-25T00:00:00Z",
            supersedes_authorization_id=scenario["window_a"],
        ),
        201,
    )

    assert window_e["status"] == "VALID"
    assert _read_authorization(api, scenario["window_a"])["status"] == "SUPERSEDED"


def test_the_valid_filter_returns_only_the_three_surviving_windows(api):
    """After the adjacency, the disjoint scope and the supersession, three windows stand.

    PRD: "Authorizations may be listed with optional `patient_id`, `requester_id`, `supersedes_authorization_id` and `status` filters."

    Design: Difficulty/resource_temporal_overlap/authorization_coverage_half_open_allows_adjacency
    """
    scenario = _patient_holding_window_a(api)
    validate_error(
        _propose_window(api, scenario, "2026-08-15T00:00:00Z", "2026-10-01T00:00:00Z"),
        e.ERR_AUTHORIZATION_WINDOW_OVERLAP,
        409,
    )
    window_c = validate_success(
        _propose_window(api, scenario, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"), 201
    )
    window_d = validate_success(
        _propose_window(
            api,
            scenario,
            "2026-08-15T00:00:00Z",
            "2026-10-01T00:00:00Z",
            scope=["BEHAVIORAL_HEALTH"],
        ),
        201,
    )
    window_e = validate_success(
        _propose_window(
            api,
            scenario,
            "2026-08-20T00:00:00Z",
            "2026-08-25T00:00:00Z",
            supersedes_authorization_id=scenario["window_a"],
        ),
        201,
    )

    rows, meta = fx.list_authorizations_for(api, scenario["world"]["patient_id"], status="VALID")

    assert meta["total_count"] == 3
    assert sorted(row["id"] for row in rows) == sorted(
        [window_c["id"], window_d["id"], window_e["id"]]
    )


# --------------------------------------------------------------------------
# legacy_gateway_buffered_windows_collide_on_touch
# --------------------------------------------------------------------------
def _request_in_compilation_for_legacy_jobs(api):
    """One accepted third-party request whose facility runs a 30-minute legacy job with a
    10-minute buffer on either side."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(
        api, world, date_range_start="2018-01-01", date_range_end="2019-12-31"
    )
    fx.accept_request(api, request["id"])
    return {"world": world, "request_id": request["id"]}


def _open_legacy_job(api, request_id, start_at):
    payload = f.record_segment_payload(
        request_id, "GENERAL_MEDICAL", "LEGACY_ARCHIVE", legacy_job_start_at=start_at
    )
    return api.create_record_segment(payload, ANALYST_1)


def test_the_first_legacy_job_reserves_a_buffered_window_that_blocks_an_overlap(api):
    """A 09:00 job holds [08:50, 09:40], so a 09:40 job whose buffer opens at 09:30 collides.

    PRD: "It then tests the new job's **buffered window** — which begins the facility's `legacy_gateway_buffer_minutes` before `legacy_job_start_at` and ends the facility's `legacy_gateway_buffer_minutes` after the job's end, and which is closed at both ends — against the buffered window of every existing legacy segment on the same facility whose `retrieval_status` is `PENDING` or `RETRIEVED`."

    Design: Difficulty/resource_temporal_overlap/legacy_gateway_buffered_windows_collide_on_touch
    """
    scenario = _request_in_compilation_for_legacy_jobs(api)

    job_1 = validate_success(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"), 201
    )
    assert job_1["legacy_job_end_at"] == Instant("2026-08-03T09:30:00Z")
    assert job_1["retrieval_status"] == "PENDING"

    validate_error(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:40:00Z"),
        e.ERR_LEGACY_WINDOW_CONTENTION,
        409,
    )


def test_buffered_windows_that_touch_at_a_single_instant_already_collide(api):
    """A 09:50 job opens its buffer at exactly 09:40, the instant the incumbent closes.

    PRD: "Because both windows are closed at both ends, two windows that merely touch at a single endpoint already collide, and the creation is refused with `ERR_LEGACY_WINDOW_CONTENTION`."

    Design: Difficulty/resource_temporal_overlap/legacy_gateway_buffered_windows_collide_on_touch
    """
    scenario = _request_in_compilation_for_legacy_jobs(api)
    validate_success(_open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"), 201)

    validate_error(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:50:00Z"),
        e.ERR_LEGACY_WINDOW_CONTENTION,
        409,
    )


def test_one_minute_past_the_cushion_the_gateway_is_free_again(api):
    """09:51 clears the incumbent's cushion by a minute and runs through 10:21.

    PRD: "With the default 30-minute job and 10-minute buffer, a job starting on the hour occupies the gateway from ten minutes before the hour through fifty minutes past it inclusive, so the next job may not begin before fifty-one minutes past the following ten-minute cushion."

    Design: Difficulty/resource_temporal_overlap/legacy_gateway_buffered_windows_collide_on_touch
    """
    scenario = _request_in_compilation_for_legacy_jobs(api)
    validate_success(_open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"), 201)

    job_4 = validate_success(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:51:00Z"), 201
    )

    assert job_4["legacy_job_start_at"] == Instant("2026-08-03T09:51:00Z")
    assert job_4["legacy_job_end_at"] == Instant("2026-08-03T10:21:00Z")


def test_the_two_refused_jobs_left_no_segment_behind(api):
    """Four attempts, two refusals, two rows.

    PRD: "Because both windows are closed at both ends, two windows that merely touch at a single endpoint already collide, and the creation is refused with `ERR_LEGACY_WINDOW_CONTENTION`."

    Design: Difficulty/resource_temporal_overlap/legacy_gateway_buffered_windows_collide_on_touch
    """
    scenario = _request_in_compilation_for_legacy_jobs(api)
    validate_success(_open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"), 201)
    validate_error(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:40:00Z"),
        e.ERR_LEGACY_WINDOW_CONTENTION,
        409,
    )
    validate_error(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:50:00Z"),
        e.ERR_LEGACY_WINDOW_CONTENTION,
        409,
    )
    validate_success(_open_legacy_job(api, scenario["request_id"], "2026-08-03T09:51:00Z"), 201)

    rows, meta = fx.list_segments_for(
        api, scenario["request_id"], source_system="LEGACY_ARCHIVE"
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_withdrawing_a_job_releases_the_gateway_window_it_held(api):
    """Only PENDING and RETRIEVED jobs contend, so a withdrawal frees 09:00 for reuse.

    PRD: "It then tests the new job's **buffered window** — which begins the facility's `legacy_gateway_buffer_minutes` before `legacy_job_start_at` and ends the facility's `legacy_gateway_buffer_minutes` after the job's end, and which is closed at both ends — against the buffered window of every existing legacy segment on the same facility whose `retrieval_status` is `PENDING` or `RETRIEVED`."

    Design: Difficulty/resource_temporal_overlap/legacy_gateway_buffered_windows_collide_on_touch
    """
    scenario = _request_in_compilation_for_legacy_jobs(api)
    job_1 = validate_success(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"), 201
    )
    validate_success(_open_legacy_job(api, scenario["request_id"], "2026-08-03T09:51:00Z"), 201)
    validate_error(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"),
        e.ERR_LEGACY_WINDOW_CONTENTION,
        409,
    )

    get_success_data(
        api.segment_disposition(job_1["id"], f.withdrawn_payload(), ANALYST_1)
    )
    assert fx.read_segment(api, job_1["id"])["retrieval_status"] == "WITHDRAWN"

    job_5 = validate_success(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"), 201
    )
    assert job_5["legacy_job_end_at"] == Instant("2026-08-03T09:30:00Z")


def test_pending_and_withdrawn_jobs_contribute_no_pages_to_the_ledger(api):
    """Reserving the gateway is not retrieving pages.

    PRD: "Segments that are still `PENDING`, or that ended `UNAVAILABLE` or `WITHDRAWN`, appear in no aggregate."

    Design: Difficulty/resource_temporal_overlap/legacy_gateway_buffered_windows_collide_on_touch
    """
    scenario = _request_in_compilation_for_legacy_jobs(api)
    job_1 = validate_success(
        _open_legacy_job(api, scenario["request_id"], "2026-08-03T09:00:00Z"), 201
    )
    validate_success(_open_legacy_job(api, scenario["request_id"], "2026-08-03T09:51:00Z"), 201)
    get_success_data(api.segment_disposition(job_1["id"], f.withdrawn_payload(), ANALYST_1))

    request = fx.read_request(api, scenario["request_id"])
    assert request["page_count_total"] == 0
    assert request["billable_page_count"] == 0
