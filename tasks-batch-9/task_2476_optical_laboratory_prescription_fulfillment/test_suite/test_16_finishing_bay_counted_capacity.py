"""A two-chair finishing bay counted over closed intervals."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TECHNICIAN_A_HEADERS

WINDOW_A = ("2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
WINDOW_B = ("2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z")
WINDOW_C = ("2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z")
CANCEL_REASON = "BAY_RESHUFFLE"


def _bay_with_two_scheduled_windows(api):
    """BAY-1 at capacity 2, holding 10:00-11:00 and 10:30-11:30."""
    scenario = fixtures.surfaced_queued_job(api)
    assert scenario["bay"]["concurrent_capacity"] == 2

    op_a = fixtures.book_edging(api, scenario, *WINDOW_A)
    assert op_a["status"] == "SCHEDULED"
    op_b = fixtures.book_edging(api, scenario, *WINDOW_B)
    assert op_b["status"] == "SCHEDULED"

    scenario["op_a_id"] = op_a["id"]
    scenario["op_b_id"] = op_b["id"]
    return scenario


def _book_window_c(api, scenario):
    version = fixtures.read_job(api, scenario["job_id"])["version"]
    return api.create_lab_operation(
        f.create_edging_operation_payload(
            scenario["job_id"], version, scenario["bay_id"], WINDOW_C[0], WINDOW_C[1]
        ),
        TECHNICIAN_A_HEADERS,
    )


def test_a_window_that_merely_touches_an_endpoint_still_counts(api):
    """11:00-12:00 shares only the 11:00 instant with the first window, yet fills it.

    PRD 3.6: "Count the existing occupations on that bay whose start is at or before
    the requested end and whose end is at or after the requested start — closed
    intervals, so two windows that merely share an endpoint do count as overlapping."

    Design: Difficulty/resource_temporal_overlap/finishing_bay_counts_touching_windows_against_a_capacity_of_two
    """
    scenario = _bay_with_two_scheduled_windows(api)

    validate_error(
        _book_window_c(api, scenario), ApiErrorId.BAY_CAPACITY_EXCEEDED.value, 409
    )


def test_dropping_one_booking_frees_exactly_one_slot(api):
    """A CANCELLED occupation stops occupying the bay, so the same window fits.

    PRD 3.6: "In both calculations, only occupations whose `status` is `SCHEDULED` or
    `RUNNING` occupy the resource; a `CANCELLED`, `COMPLETED` or `BROKEN` occupation
    never occupies anything."

    Design: Difficulty/resource_temporal_overlap/finishing_bay_counts_touching_windows_against_a_capacity_of_two
    """
    scenario = _bay_with_two_scheduled_windows(api)
    validate_error(
        _book_window_c(api, scenario), ApiErrorId.BAY_CAPACITY_EXCEEDED.value, 409
    )

    cancelled = validate_success(
        api.cancel_lab_operation(
            scenario["op_a_id"], {"cancel_reason": CANCEL_REASON}, TECHNICIAN_A_HEADERS
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == CANCEL_REASON

    op_c = validate_success(_book_window_c(api, scenario), expected_status=201)
    assert op_c["status"] == "SCHEDULED"
    assert op_c["window_start"] == "2026-08-01T11:00:00.000Z"


def test_none_of_the_bookings_advance_the_job(api):
    """The job stays QUEUED across three accepted bookings and one rejection.

    PRD 3.6: "Production happens inside **occupations** — bounded windows during which
    one job holds one machine or one bay."

    Design: Difficulty/resource_temporal_overlap/finishing_bay_counts_touching_windows_against_a_capacity_of_two
    """
    scenario = _bay_with_two_scheduled_windows(api)
    assert fixtures.read_job(api, scenario["job_id"])["status"] == "QUEUED"

    validate_error(
        _book_window_c(api, scenario), ApiErrorId.BAY_CAPACITY_EXCEEDED.value, 409
    )
    validate_success(
        api.cancel_lab_operation(
            scenario["op_a_id"], {"cancel_reason": CANCEL_REASON}, TECHNICIAN_A_HEADERS
        )
    )
    validate_success(_book_window_c(api, scenario), expected_status=201)

    assert fixtures.read_job(api, scenario["job_id"])["status"] == "QUEUED"
