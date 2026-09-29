"""Temporal overlap: a half-open interval, a status-filtered peer set, a closed interval."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


# ─── The half-open appraisal validity interval ────────────────────────────────

def _draft_initial_appraisal(api, parcel_id, effective_date, indicated_value_cents,
                             headers=None):
    return validate_success(
        api.create_appraisal(
            parcel_id,
            factories.create_appraisal_payload(
                parcel_id,
                appraiser_license_no="LIC-SA-2",
                effective_date=effective_date,
                indicated_value_cents=indicated_value_cents,
            ),
            headers or TEST_USERS["staff_appraiser_2_headers"],
        ),
        201,
    )


def _parcel_with_accepted_window_and_a_touching_draft(api):
    """Appraisal A accepted over [2026-07-01, 2027-07-01) and B drafted at its close."""
    state = fixtures.create_approved_project(api)
    state["appraisal_a"] = fixtures.accepted_initial_appraisal(
        api, state["parcel"]["id"], effective_date="2026-07-01",
        indicated_value_cents=20_000_000,
    )
    state["appraisal_b"] = _draft_initial_appraisal(
        api, state["parcel"]["id"], "2027-07-01", 21_000_000
    )
    return state


def test_a_window_opening_exactly_where_the_previous_one_closes_may_submit(api):
    """The instant that closes one validity interval opens the next one.

    "The validity interval is **half-open**: it includes `effective_date` and
    excludes `validity_end_date`."

    "Because both comparisons are strict, intervals that merely touch - where one
    appraisal's `validity_end_date` equals the next one's `effective_date` - do
    **not** overlap and both may coexist."

    Design: Difficulty/resource_temporal_overlap/appraisal_half_open_validity_windows_touching_at_the_boundary_are_permitted
    """
    state = _parcel_with_accepted_window_and_a_touching_draft(api)
    assert state["appraisal_a"]["validity_end_date"] == "2027-07-01"
    assert state["appraisal_a"]["status"] == "ACCEPTED"

    submitted = validate_success(
        api.submit_appraisal(
            state["appraisal_b"]["id"], TEST_USERS["staff_appraiser_2_headers"]
        )
    )

    assert submitted["status"] == "SUBMITTED"
    assert submitted["effective_date"] == "2027-07-01"
    assert submitted["validity_end_date"] == "2028-07-01"


def test_both_touching_appraisals_coexist_on_the_same_parcel(api):
    """Neither row displaces the other, so the parcel carries two initial opinions.

    "Two `INITIAL` appraisals on the same parcel, both with `status` of `SUBMITTED`
    or `ACCEPTED`, overlap when the first's `effective_date` is strictly earlier
    than the second's `validity_end_date` **and** the second's `effective_date` is
    strictly earlier than the first's `validity_end_date`."

    "An overlap is refused with `ERR_APPRAISAL_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appraisal_half_open_validity_windows_touching_at_the_boundary_are_permitted
    """
    state = _parcel_with_accepted_window_and_a_touching_draft(api)
    validate_success(
        api.submit_appraisal(
            state["appraisal_b"]["id"], TEST_USERS["staff_appraiser_2_headers"]
        )
    )

    rows, _meta = validate_paginated(
        api.list_appraisals(
            TEST_USERS["program_administrator_headers"],
            params={"parcel_id": state["parcel"]["id"], "appraisal_type": "INITIAL"},
        )
    )
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"ACCEPTED", "SUBMITTED"}


# ─── The status-filtered peer set ─────────────────────────────────────────────

def _parcel_with_three_overlapping_drafts(api):
    """One accepted window plus drafts D, E and F whose windows chain into each other."""
    state = fixtures.create_approved_project(api)
    state["appraisal_a"] = fixtures.accepted_initial_appraisal(
        api, state["parcel"]["id"], effective_date="2026-07-01",
        indicated_value_cents=20_000_000,
    )
    state["appraisal_d"] = _draft_initial_appraisal(
        api, state["parcel"]["id"], "2027-06-30", 21_000_000
    )
    state["appraisal_e"] = _draft_initial_appraisal(
        api, state["parcel"]["id"], "2028-01-01", 22_000_000
    )
    state["appraisal_f"] = _draft_initial_appraisal(
        api, state["parcel"]["id"], "2028-06-30", 23_000_000
    )
    return state


def _submit(api, appraisal_id):
    return api.submit_appraisal(appraisal_id, TEST_USERS["staff_appraiser_2_headers"])


def test_a_single_day_of_overlap_with_an_accepted_peer_is_refused(api):
    """One day inside the accepted window is enough to fail the strict comparison.

    "An overlap is refused with `ERR_APPRAISAL_WINDOW_OVERLAP`."

    "On submission the server computes `validity_end_date` as `effective_date`
    plus 12 calendar months, clamped to month end where the anchor day-of-month
    does not exist in the target month."

    Design: Difficulty/resource_temporal_overlap/appraisal_windows_overlapping_by_one_day_conflict_only_once_the_peer_is_submitted
    """
    state = _parcel_with_three_overlapping_drafts(api)

    validate_error(
        _submit(api, state["appraisal_d"]["id"]),
        ApiErrorId.ERR_APPRAISAL_WINDOW_OVERLAP.value,
        409,
    )

    appraisal = validate_success(
        api.get_appraisal(
            state["appraisal_d"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert appraisal["status"] == "DRAFT"


def test_a_draft_peer_is_invisible_until_it_is_itself_submitted(api):
    """The same pair of intervals is legal or illegal depending on the peer's state.

    "First, the peer set is restricted to appraisals in `SUBMITTED` or `ACCEPTED`:
    appraisals sitting in `DRAFT`, `RETURNED_FOR_REVISION` or `REJECTED` are
    invisible to it, so a rejected appraisal never blocks a fresh one over the
    same period."

    "A submission from `RETURNED_FOR_REVISION` re-runs the overlap check against
    the possibly revised `effective_date`."

    Design: Difficulty/resource_temporal_overlap/appraisal_windows_overlapping_by_one_day_conflict_only_once_the_peer_is_submitted
    """
    state = _parcel_with_three_overlapping_drafts(api)
    validate_error(
        _submit(api, state["appraisal_d"]["id"]),
        ApiErrorId.ERR_APPRAISAL_WINDOW_OVERLAP.value,
        409,
    )

    submitted = validate_success(_submit(api, state["appraisal_e"]["id"]))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["validity_end_date"] == "2029-01-01"

    validate_error(
        _submit(api, state["appraisal_f"]["id"]),
        ApiErrorId.ERR_APPRAISAL_WINDOW_OVERLAP.value,
        409,
    )
    blocked = validate_success(
        api.get_appraisal(
            state["appraisal_f"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert blocked["status"] == "DRAFT"


# ─── The closed buffered window and aggregate capacity ────────────────────────

def _five_parcel_project_with_two_contractors(api):
    project = fixtures.create_draft_project(api)
    parcels = [
        fixtures.create_parcel(
            api,
            project,
            apn=f"APN-RC{index}",
            site_address=f"90{index} River Rd",
            acreage=0.30,
            occupancy_type="VACANT",
        )
        for index in range(1, 6)
    ]
    delta = fixtures.create_contractor(
        api, name="Delta Demolition", license_no="DEM-D",
        asbestos_certified=True, max_concurrent_work_orders=2,
    )
    epsilon = fixtures.create_contractor(
        api, name="Epsilon Demolition", license_no="DEM-E",
        asbestos_certified=True, max_concurrent_work_orders=1,
    )
    first_delta = fixtures.issue_work_order(
        api, project, parcels[0]["id"], delta["id"],
        scheduled_start="2026-10-05T08:00:00Z", scheduled_end="2026-10-06T17:00:00Z",
    )
    first_epsilon = fixtures.issue_work_order(
        api, project, parcels[3]["id"], epsilon["id"],
        scheduled_start="2026-11-05T08:00:00Z", scheduled_end="2026-11-06T17:00:00Z",
    )
    return {
        "project": project,
        "parcels": parcels,
        "delta": delta,
        "epsilon": epsilon,
        "delta_first": first_delta,
        "epsilon_first": first_epsilon,
    }


def _issue(api, project, parcel_id, contractor_id, scheduled_start, scheduled_end):
    return api.create_demolition_work_order(
        parcel_id,
        factories.create_work_order_payload(
            parcel_id,
            contractor_id,
            asbestos_survey_status="NOT_PERFORMED",
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        make_subrecipient_coordinator_headers(project["id"]),
    )


def test_one_conflicting_window_is_admitted_while_capacity_remains(api):
    """A conflicting pair is legal on its own because the count is still under the cap.

    "`buffered_start` is `scheduled_start` minus 24 hours and `buffered_end` is
    `scheduled_end` plus 24 hours, and the buffered occupation interval is
    **closed** - both endpoints are included."

    "So with a `max_concurrent_work_orders` of 2, two mutually conflicting work
    orders are perfectly legal and a third conflicting one is rejected: each row
    is individually permissible, and it is the collective that exceeds capacity."

    Design: Difficulty/resource_temporal_overlap/demolition_buffered_windows_touch_and_conflict_at_contractor_aggregate_capacity
    """
    state = _five_parcel_project_with_two_contractors(api)
    assertions.assert_buffered_window(
        state["delta_first"], "2026-10-04T08:00:00Z", "2026-10-07T17:00:00Z"
    )

    second = validate_success(
        _issue(
            api, state["project"], state["parcels"][1]["id"], state["delta"]["id"],
            "2026-10-08T09:00:00Z", "2026-10-08T17:00:00Z",
        ),
        201,
    )

    assertions.assert_buffered_window(
        second, "2026-10-07T09:00:00Z", "2026-10-09T17:00:00Z"
    )


def test_a_third_conflicting_window_exceeds_the_aggregate_capacity(api):
    """No individual pair explains the refusal; the collective does.

    "The check is an aggregate capacity check rather than a pairwise ban. Issuing
    a work order is refused with `ERR_DEMOLITION_WINDOW_CONFLICT` when the number
    of existing conflicting work orders found for that contractor is at least
    `max_concurrent_work_orders`."

    "`active_work_order_count` is the count of that contractor's work orders whose
    `status` is `ISSUED`, `UTILITY_HOLD`, `READY`, `IN_PROGRESS` or
    `FAILED_INSPECTION`."

    Design: Difficulty/resource_temporal_overlap/demolition_buffered_windows_touch_and_conflict_at_contractor_aggregate_capacity
    """
    state = _five_parcel_project_with_two_contractors(api)
    validate_success(
        _issue(
            api, state["project"], state["parcels"][1]["id"], state["delta"]["id"],
            "2026-10-08T09:00:00Z", "2026-10-08T17:00:00Z",
        ),
        201,
    )

    validate_error(
        _issue(
            api, state["project"], state["parcels"][2]["id"], state["delta"]["id"],
            "2026-10-07T10:00:00Z", "2026-10-07T14:00:00Z",
        ),
        ApiErrorId.ERR_DEMOLITION_WINDOW_CONFLICT.value,
        409,
    )

    contractor = validate_success(
        api.get_demolition_contractor(
            state["delta"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert contractor["active_work_order_count"] == 2

    rows, _meta = validate_paginated(
        api.list_demolition_work_orders(
            TEST_USERS["program_administrator_headers"],
            params={"contractor_id": state["delta"]["id"]},
        )
    )
    assert len(rows) == 2


def test_buffered_windows_that_merely_touch_conflict_and_one_second_clears_it(api):
    """The closed convention makes the touching instant a conflict, unlike the appraisal interval.

    "Because both comparisons are non-strict, buffered windows that merely touch -
    where one's `buffered_end` equals the other's `buffered_start` - **do**
    conflict."

    "This is the opposite convention from the appraisal validity interval in §3.4,
    and the difference is intentional."

    Design: Difficulty/resource_temporal_overlap/demolition_buffered_windows_touch_and_conflict_at_contractor_aggregate_capacity
    """
    state = _five_parcel_project_with_two_contractors(api)
    assertions.assert_instant_equals(
        state["epsilon_first"]["buffered_end"], "2026-11-07T17:00:00Z", "buffered_end"
    )

    validate_error(
        _issue(
            api, state["project"], state["parcels"][4]["id"], state["epsilon"]["id"],
            "2026-11-08T17:00:00Z", "2026-11-08T20:00:00Z",
        ),
        ApiErrorId.ERR_DEMOLITION_WINDOW_CONFLICT.value,
        409,
    )

    cleared = validate_success(
        _issue(
            api, state["project"], state["parcels"][4]["id"], state["epsilon"]["id"],
            "2026-11-08T17:00:01Z", "2026-11-08T20:00:00Z",
        ),
        201,
    )
    assertions.assert_instant_equals(
        cleared["buffered_start"], "2026-11-07T17:00:01Z", "buffered_start"
    )

    contractor = validate_success(
        api.get_demolition_contractor(
            state["epsilon"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert contractor["active_work_order_count"] == 2
