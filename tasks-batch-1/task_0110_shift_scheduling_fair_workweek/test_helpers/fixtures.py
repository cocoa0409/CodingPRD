"""Composite setup helpers.

The harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. All
setup calls go through get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" rather than a confusing assertion error.

Conventions (mirroring the contract):
  - Manager mutations use make_manager_headers() (opaque operator id).
  - Worker-owned actions use make_worker_headers(worker_id) with the real id.
  - The logical clock is pinned with set_clock() before time-sensitive steps.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_location_payload, create_worker_payload, create_pay_period_payload,
    create_shift_payload, create_assignment_payload, create_bid_payload,
    create_swap_payload, create_availability_payload, create_time_off_payload,
    create_shift_template_payload,
)
from .test_users import make_manager_headers, make_worker_headers
from .constants import TEST_DEFAULTS


# --- Primitive steps -------------------------------------------------------
def set_clock(api, iso, headers=None):
    headers = headers or make_manager_headers()
    return get_success_data(api.set_clock(iso, headers))


def setup_location(api, **overrides):
    """Create a Location. Returns the location dict."""
    headers = make_manager_headers()
    payload = create_location_payload(**overrides)
    return get_success_data(api.create_location(payload, headers))


def setup_worker(api, loc_id, **overrides):
    """Register a Worker at a location. Returns the worker dict."""
    headers = make_manager_headers()
    payload = create_worker_payload(**overrides)
    return get_success_data(api.create_worker(loc_id, payload, headers))


def setup_pay_period(api, loc_id, **overrides):
    """Create a PayPeriod. Returns the pay-period dict."""
    headers = make_manager_headers()
    payload = create_pay_period_payload(**overrides)
    return get_success_data(api.create_pay_period(loc_id, payload, headers))


def create_draft_shift(api, loc_id, **overrides):
    """Create an ad-hoc DRAFT shift. Returns the shift dict."""
    headers = make_manager_headers()
    payload = create_shift_payload(**overrides)
    return get_success_data(api.create_shift(loc_id, payload, headers))


def create_posted_shift(api, loc_id, **overrides):
    """Create a shift and post it to OPEN. Returns the (re-read) OPEN shift dict."""
    headers = make_manager_headers()
    shift = create_draft_shift(api, loc_id, **overrides)
    return get_success_data(api.post_shift(loc_id, shift["id"], headers))


def assign_worker(api, loc_id, shift_id, worker_id, **overrides):
    """Directly assign a worker to an OPEN shift. Returns the assignment dict."""
    headers = make_manager_headers()
    payload = create_assignment_payload(shift_id, worker_id, **overrides)
    return get_success_data(api.create_assignment(loc_id, payload, headers))


# --- Tier 2: small hierarchies --------------------------------------------
def setup_location_worker_payperiod(loc_overrides=None, worker_overrides=None,
                                    pp_overrides=None, clock_iso="2026-06-01T00:00:00Z",
                                    api=None):
    """Pin clock, create Location + one Worker + one PayPeriod.
    Returns (location, worker, pay_period)."""
    api = api or api_client
    set_clock(api, clock_iso)
    loc = setup_location(api, **(loc_overrides or {}))
    worker = setup_worker(api, loc["id"], **(worker_overrides or {}))
    pp = setup_pay_period(api, loc["id"], **(pp_overrides or {}))
    return loc, worker, pp


def setup_open_shift_with_assignment(loc_overrides=None, worker_overrides=None,
                                     shift_overrides=None, pp_overrides=None,
                                     clock_iso="2026-06-01T00:00:00Z", api=None):
    """Location + worker + pay-period + one OPEN shift with the worker SCHEDULED.
    Returns (location, worker, pay_period, shift, assignment)."""
    api = api or api_client
    loc, worker, pp = setup_location_worker_payperiod(
        loc_overrides, worker_overrides, pp_overrides, clock_iso, api)
    shift = create_posted_shift(api, loc["id"], **(shift_overrides or {}))
    asg = assign_worker(api, loc["id"], shift["id"], worker["id"])
    return loc, worker, pp, shift, asg


# --- Tier 3: lifecycle shortcuts ------------------------------------------
def setup_completed_shift_with_assignment(loc_overrides=None, worker_overrides=None,
                                          shift_overrides=None, pp_overrides=None,
                                          clock_iso="2026-06-01T00:00:00Z",
                                          complete_clock_iso="2026-06-05T13:00:01Z",
                                          api=None):
    """Build an OPEN shift with one SCHEDULED assignment, then advance the clock
    past the shift end and complete it (cascades the assignment to COMPLETED).
    Returns (location, worker, pay_period, shift, assignment) — assignment re-read."""
    api = api or api_client
    loc, worker, pp, shift, asg = setup_open_shift_with_assignment(
        loc_overrides, worker_overrides, shift_overrides, pp_overrides, clock_iso, api)
    set_clock(api, complete_clock_iso)
    headers = make_manager_headers()
    get_success_data(api.complete_shift(loc["id"], shift["id"], headers))
    asg = get_success_data(api.get_assignment(asg["id"], headers))
    return loc, worker, pp, shift, asg


def setup_worker_with_strikes(num_strikes, loc_overrides=None, worker_overrides=None,
                              api=None, clock_iso="2026-06-01T00:00:00Z"):
    """Drive a worker to exactly `num_strikes` no-show strikes by scheduling and
    no-showing `num_strikes` short shifts on distinct days. Returns
    (location, worker, pay_period). The worker is SUSPENDED iff num_strikes >= 3.
    Each no-show requires the clock to have reached that shift's start."""
    api = api or api_client
    loc, worker, pp = setup_location_worker_payperiod(
        loc_overrides, worker_overrides, None, clock_iso, api)
    headers = make_manager_headers()
    for i in range(num_strikes):
        day = 2 + i  # 2026-06-02, -03, -04, ...
        shift = create_posted_shift(
            api, loc["id"],
            start_utc=f"2026-06-{day:02d}T09:00:00Z",
            end_utc=f"2026-06-{day:02d}T13:00:00Z",
            headcount_required=1,
        )
        asg = assign_worker(api, loc["id"], shift["id"], worker["id"])
        set_clock(api, f"2026-06-{day:02d}T09:00:01Z")
        get_success_data(api.no_show_assignment(loc["id"], asg["id"], headers))
    worker = get_success_data(api.get_worker(worker["id"], headers))
    return loc, worker, pp


def setup_bid_on_open_shift(seniority_score=0, loc_overrides=None, worker_overrides=None,
                            shift_overrides=None, pp_overrides=None,
                            clock_iso="2026-06-01T00:00:00Z", api=None):
    """Location + worker + pay-period + OPEN shift + one SUBMITTED bid from the worker.
    Returns (location, worker, pay_period, shift, bid). The shift dict carries the
    version observed right after posting (use shift['version'] for expected_shift_version)."""
    api = api or api_client
    loc, worker, pp = setup_location_worker_payperiod(
        loc_overrides, worker_overrides, pp_overrides, clock_iso, api)
    shift = create_posted_shift(api, loc["id"], **(shift_overrides or {}))
    bid = get_success_data(api.create_bid(
        loc["id"], shift["id"], create_bid_payload(seniority_score=seniority_score),
        make_worker_headers(worker["id"])))
    return loc, worker, pp, shift, bid


def setup_swap_proposed(loc_overrides=None, pp_overrides=None,
                        clock_iso="2026-06-01T00:00:00Z", api=None,
                        shift_a_overrides=None, shift_b_overrides=None):
    """Two workers WA/WB, each owning one SCHEDULED assignment; WA proposes a swap
    of its assignment to WB. Returns (location, pay_period, wa, wb, a_a, a_b, swap)."""
    api = api or api_client
    set_clock(api, clock_iso)
    loc = setup_location(api, **(loc_overrides or {}))
    wa = setup_worker(api, loc["id"], full_name="WA", email="wa@x.com")
    wb = setup_worker(api, loc["id"], full_name="WB", email="wb@x.com")
    pp = setup_pay_period(api, loc["id"], **(pp_overrides or {}))
    shift_a = create_posted_shift(
        api, loc["id"],
        **(shift_a_overrides or dict(start_utc="2026-06-02T09:00:00Z",
                                     end_utc="2026-06-02T13:00:00Z", headcount_required=1)))
    a_a = assign_worker(api, loc["id"], shift_a["id"], wa["id"])
    shift_b = create_posted_shift(
        api, loc["id"],
        **(shift_b_overrides or dict(start_utc="2026-06-03T09:00:00Z",
                                     end_utc="2026-06-03T13:00:00Z", headcount_required=1)))
    a_b = assign_worker(api, loc["id"], shift_b["id"], wb["id"])
    swap = get_success_data(api.create_swap(
        loc["id"], create_swap_payload(a_a["id"], wb["id"]),
        make_worker_headers(wa["id"])))
    return loc, pp, wa, wb, a_a, a_b, swap


def add_availability(api, worker_id, **overrides):
    """Add an availability/unavailability window. Returns the window dict."""
    payload = create_availability_payload(**overrides)
    return get_success_data(api.create_availability(
        worker_id, payload, make_worker_headers(worker_id)))


def add_time_off(api, worker_id, **overrides):
    """Submit a PENDING time-off request for the worker. Returns the request dict."""
    payload = create_time_off_payload(**overrides)
    return get_success_data(api.create_time_off(
        worker_id, payload, make_worker_headers(worker_id)))


def setup_shift_template(api, loc_id, **overrides):
    """Create a ShiftTemplate. Returns the template dict."""
    payload = create_shift_template_payload(**overrides)
    return get_success_data(api.create_shift_template(loc_id, payload, make_manager_headers()))
