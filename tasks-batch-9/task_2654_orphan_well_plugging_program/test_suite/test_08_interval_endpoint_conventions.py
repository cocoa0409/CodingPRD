"""Two occupancy intervals with deliberately opposite endpoint conventions."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_ACCESS_WINDOW_CONFLICT,
    ERR_CREW_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_page,
    created,
)
from test_helpers.factories import plugging_job_payload, site_access_payload


def _one_crew_two_wells(api):
    """Two confirmed orphan wells and one contractor already booked 09-01 to 09-06."""
    operator = fx.make_unbonded_operator(
        api,
        name="Sabine Legacy Wells",
        region_code="TX",
        financial_assurance_tier="BLANKET",
    )
    first = fx.make_confirmed_orphan_well(api, operator=operator)
    second = fx.make_confirmed_orphan_well(api, operator=operator, total_depth_ft=2600)
    procurement = fx.make_active_contract(
        api,
        region_code="TX",
        scope_description="two-well orphan plugging package",
    )
    job = fx.make_plugging_job(
        api,
        first["well"]["id"],
        procurement["contract"]["id"],
        scheduled_start="2026-09-01T00:00:00Z",
    )
    return {
        "operator": operator,
        "first_well": first["well"],
        "second_well": second["well"],
        "contract": procurement["contract"],
        "job": job,
    }


def test_a_second_job_starting_inside_the_crew_window_is_refused(api):
    """Three rig days plus two buffer days occupy 09-01 through 09-05.

    A job proposed for 09-05 falls strictly inside the first job's half-open interval,
    so the same crew would be in two places at once and the order is refused with
    nothing obligated for it.

    PRD: "The job's `crew_window_end_at` is derived as `scheduled_start` plus
    `planned_rig_days` plus 2 further days of demobilization buffer."

    Design: Difficulty/resource_temporal_overlap/contractor_crew_window_is_half_open_so_touching_jobs_are_allowed
    """
    bundle = _one_crew_two_wells(api)
    assert_fields(bundle["job"], crew_window_end_at="2026-09-06T00:00:00Z")

    refused = api.create_plugging_job(
        plugging_job_payload(
            bundle["second_well"]["id"],
            bundle["contract"]["id"],
            scheduled_start="2026-09-05T00:00:00Z",
        ),
        users.ADMIN,
    )
    validate_error(refused, ERR_CREW_WINDOW_CONFLICT)

    assert_fields(
        fx.read_well(api, bundle["second_well"]["id"]), status="ORPHAN_CONFIRMED"
    )
    assert_cents(
        fx.read_contract(api, bundle["contract"]["id"])["obligated_cents"],
        6070196,
        "obligated_cents",
    )


def test_a_second_job_starting_exactly_at_the_window_end_is_accepted(api):
    """Back-to-back scheduling is legal because the crew interval excludes its end.

    A job starting on the very instant the first window ends does not overlap it, so
    the order is accepted, gets its own window and doubles the contract's obligation.

    PRD: "Because the interval is half-open, back-to-back scheduling is legal: a job
    whose `scheduled_start` falls exactly on another job's `crew_window_end_at` does
    **not** conflict."

    Design: Difficulty/resource_temporal_overlap/contractor_crew_window_is_half_open_so_touching_jobs_are_allowed
    """
    bundle = _one_crew_two_wells(api)

    second_job = created(
        api.create_plugging_job(
            plugging_job_payload(
                bundle["second_well"]["id"],
                bundle["contract"]["id"],
                scheduled_start="2026-09-06T00:00:00Z",
            ),
            users.ADMIN,
        )
    )
    assert_fields(
        second_job,
        status="SCHEDULED",
        scheduled_start="2026-09-06T00:00:00Z",
        crew_window_end_at="2026-09-11T00:00:00Z",
    )
    assert_cents(
        second_job["plugging_cost_estimate_cents"], 6070196, "plugging_cost_estimate_cents"
    )
    assert_cents(
        fx.read_contract(api, bundle["contract"]["id"])["obligated_cents"],
        12140392,
        "obligated_cents",
    )
    assert_fields(
        fx.read_well(api, bundle["second_well"]["id"]), status="PLUGGING_SCHEDULED"
    )


def _well_under_a_running_notice(api):
    """A well whose statutory notice window runs from 2026-08-10 to 2026-09-09."""
    operator = fx.make_operator(
        api, name="Cypress Bayou Minerals", region_code="LA", bond_amount_cents=5000000
    )
    well = fx.make_well(api, operator["id"], spud_year=1979)
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    access = fx.open_site_access(
        api,
        well["id"],
        mode="STATUTORY_ENTRY",
        surface_owner_name="Renard Boudreaux",
        waiting_period_days=30,
        compensation_cents=0,
    )
    return {"operator": operator, "well": well, "access": access}


def test_notice_windows_that_merely_touch_do_conflict(api):
    """A second notice starting on the first window's last instant is refused.

    Both intervals are closed, so they share the instant 2026-09-09 and overlap; the
    create is rejected and the well keeps its single live request.

    PRD: "Because both intervals are closed, **windows that merely touch at an endpoint
    do conflict** — a new request whose `notice_sent_at` falls exactly on an existing
    window's `window_end_at` is refused."

    Design: Difficulty/resource_temporal_overlap/site_access_notice_window_is_closed_so_touching_requests_conflict
    """
    bundle = _well_under_a_running_notice(api)
    well_id = bundle["well"]["id"]
    assert_fields(
        bundle["access"],
        notice_sent_at="2026-08-10T00:00:00Z",
        window_end_at="2026-09-09T00:00:00Z",
    )

    fx.set_clock(api, "2026-09-09T00:00:00Z")

    refused = api.create_site_access(
        well_id,
        site_access_payload(
            mode="STATUTORY_ENTRY",
            surface_owner_name="Renard Boudreaux Estate",
            waiting_period_days=30,
            compensation_cents=0,
        ),
        users.ADMIN,
    )
    validate_error(refused, ERR_ACCESS_WINDOW_CONFLICT)

    assert_page(api.list_well_site_accesses(well_id, users.ADMIN), 1, expected_total=1)
    assert_fields(fx.read_well(api, well_id), access_status="ACCESS_PENDING")


def test_a_denied_notice_frees_the_well_once_its_window_has_elapsed(api):
    """Denial resolves the row, and a fresh notice is possible past the old window.

    The denial projects ACCESS_DENIED onto the well, and once the denied row's closed
    window has ended strictly before the clock a new request is accepted and opens its
    own thirty-day window.

    PRD: "Denying the request moves the row `REQUESTED → DENIED`, sets `resolved_at`,
    and mirrors the well to `ACCESS_PENDING → ACCESS_DENIED`."

    Design: Difficulty/resource_temporal_overlap/site_access_notice_window_is_closed_so_touching_requests_conflict
    """
    bundle = _well_under_a_running_notice(api)
    well_id = bundle["well"]["id"]

    fx.set_clock(api, "2026-09-09T00:00:00Z")
    denied = fx.resolve_site_access(api, bundle["access"]["id"], "DENY")
    assert_fields(denied, status="DENIED", resolved_at="2026-09-09T00:00:00Z")
    assert_fields(fx.read_well(api, well_id), access_status="ACCESS_DENIED")

    fx.set_clock(api, "2026-09-10T00:00:00Z")
    replacement = created(
        api.create_site_access(
            well_id,
            site_access_payload(
                mode="STATUTORY_ENTRY",
                surface_owner_name="Renard Boudreaux Estate",
                waiting_period_days=30,
                compensation_cents=0,
            ),
            users.ADMIN,
        )
    )
    assert_fields(
        replacement,
        status="REQUESTED",
        notice_sent_at="2026-09-10T00:00:00Z",
        window_end_at="2026-10-10T00:00:00Z",
    )
    assert_fields(fx.read_well(api, well_id), access_status="ACCESS_PENDING")
    assert_page(api.list_well_site_accesses(well_id, users.ADMIN), 2, expected_total=2)
