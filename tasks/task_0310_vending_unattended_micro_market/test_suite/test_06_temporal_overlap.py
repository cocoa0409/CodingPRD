"""Half-open interval overlap rules: route-stop service windows for one driver
on one service date, and commission-statement periods for one host.
"""
from test_helpers import validate_success, validate_error, api_client
from test_helpers import (
    set_clock, make_host, make_machine, make_driver, make_route, make_stop,
    make_statement,
)
from test_helpers.test_users import TEST_USERS

FIELD_OPS = TEST_USERS["field_ops_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


# ─── resource_temporal_overlap / rto_driver_window_half_open_overlap_rejected ─

def test_overlapping_driver_window_rejected():
    """PRD §3.4: "Because windows are half-open, two stops whose windows merely
    touch at a shared endpoint do not overlap and are allowed; any true overlap is
    rejected with ERR_DRIVER_WINDOW_OVERLAP (HTTP 409)."

    A stop [500,560) truly overlaps an existing [480,540) (they share [500,540))
    for the same driver and service_date.

    Design: Difficulty/resource_temporal_overlap/rto_driver_window_half_open_overlap_rejected
    """
    set_clock("2026-06-09T00:00:00Z")
    host = make_host(name="Win Host", contact_email="w@x.com")
    machineA = make_machine(host["id"], asset_tag="M-14", machine_type="SNACK_VENDOR")
    machineB = make_machine(host["id"], asset_tag="M-15", machine_type="SNACK_VENDOR")
    driver = make_driver(full_name="Wendy", employee_code="EMP14")
    route = make_route(driver["id"], "2026-06-09T00:00:00Z")
    make_stop(route["id"], machineA["id"], 480, 540)

    res = api_client.create_stop(
        route["id"], {"machine_id": machineB["id"], "window_start_min": 500, "window_end_min": 560},
        FIELD_OPS)
    validate_error(res, "ERR_DRIVER_WINDOW_OVERLAP", expected_status=409)


def test_touching_driver_windows_allowed():
    """PRD §3.4: "two stops whose windows merely touch at a shared endpoint do not
    overlap and are allowed; any true overlap is rejected with
    ERR_DRIVER_WINDOW_OVERLAP (HTTP 409)."

    A stop [540,600) merely touches the existing [480,540) at minute 540 and is
    accepted (the open right endpoint is exclusive).

    Design: Difficulty/resource_temporal_overlap/rto_driver_window_half_open_overlap_rejected
    """
    set_clock("2026-06-09T00:00:00Z")
    host = make_host(name="Win Host 2", contact_email="w2@x.com")
    machineA = make_machine(host["id"], asset_tag="M-14b", machine_type="SNACK_VENDOR")
    machineB = make_machine(host["id"], asset_tag="M-15b", machine_type="SNACK_VENDOR")
    driver = make_driver(full_name="Wendy2", employee_code="EMP14b")
    route = make_route(driver["id"], "2026-06-09T00:00:00Z")
    make_stop(route["id"], machineA["id"], 480, 540)

    res = api_client.create_stop(
        route["id"], {"machine_id": machineB["id"], "window_start_min": 540, "window_end_min": 600},
        FIELD_OPS)
    stop2 = validate_success(res, 201)
    assert stop2["window_start_min"] == 540, stop2
    assert stop2["window_end_min"] == 600, stop2


# ─── resource_temporal_overlap / rto_statement_period_overlap_rejected ─────

def test_overlapping_statement_period_rejected():
    """PRD §3.7: "A host's statements may not overlap in time: the half-open
    period from period_start up to but not including period_end must not overlap an
    existing statement for the same host_site_id, although an existing statement
    whose period_end equals the new period_start is allowed (touching boundaries
    do not overlap). A true overlap is rejected with ERR_STATEMENT_PERIOD_OVERLAP
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_statement_period_overlap_rejected
    """
    set_clock("2026-06-09T00:00:00Z")
    host = make_host(name="Per Host", contact_email="per@x.com")
    make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    res = api_client.create_statement(
        {"host_site_id": host["id"], "period_start": "2026-06-15T00:00:00Z", "period_end": "2026-07-15T00:00:00Z"},
        FINANCE)
    validate_error(res, "ERR_STATEMENT_PERIOD_OVERLAP", expected_status=409)


def test_touching_statement_period_allowed():
    """PRD §3.7: "an existing statement whose period_end equals the new
    period_start is allowed (touching boundaries do not overlap)."

    A new period starting exactly at the prior period's end is accepted.

    Design: Difficulty/resource_temporal_overlap/rto_statement_period_overlap_rejected
    """
    set_clock("2026-06-09T00:00:00Z")
    host = make_host(name="Per Host 2", contact_email="per2@x.com")
    make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    res = api_client.create_statement(
        {"host_site_id": host["id"], "period_start": "2026-07-01T00:00:00Z", "period_end": "2026-08-01T00:00:00Z"},
        FINANCE)
    stmt2 = validate_success(res, 201)
    assert stmt2["status"] == "OPEN", stmt2
