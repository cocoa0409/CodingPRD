"""Service-request TRIAGED <-> ASSIGNED revision cycle.

Queue A (Difficulty):
non_linear_state_machine/service_triaged_assigned_triaged_cycle.
"""
from test_helpers import (
    fixtures as fx,
    make_property_manager_headers,
    validate_success,
)


def _setup_reassigned_request(api):
    """HVAC request triaged, assigned, unassigned (back to TRIAGED), then
    assigned again. Returns (sr_id, vendor_id)."""
    ctx = fx.setup_assigned_request(
        api, trade="HVAC", estimated_hours=3,
        triage_user="pm_triage", assign_user="pm_assign",
        vendor_overrides={"name": "CoolCo", "trades": ["HVAC"], "hourly_rate_cents": 9000, "active_job_limit": 5},
    )
    sr_id = ctx["sr"]["id"]
    vendor_id = ctx["vendor"]["id"]
    assign_hdr = make_property_manager_headers("pm_assign")
    validate_success(api.unassign_service_request(sr_id, assign_hdr))
    validate_success(api.assign_service_request(sr_id, {"vendor_id": vendor_id, "estimated_hours": 3}, assign_hdr))
    return sr_id, vendor_id


def test_request_reassigned_after_unassign(api):
    """PRD §3.5: "A manager may unassign an `ASSIGNED` request, reverting it to
    `TRIAGED`: the vendor's `active_job_count` is decreased by one and both
    `vendor_id` and `estimated_cost_cents` are cleared to null."

    After assign -> unassign -> assign, the request is ASSIGNED again — a
    genuine TRIAGED <-> ASSIGNED cycle.

    Design: Difficulty/non_linear_state_machine/service_triaged_assigned_triaged_cycle
    """
    sr_id, _ = _setup_reassigned_request(api)
    fetched = validate_success(api.get_service_request(sr_id, fx.PM))
    assert fetched["status"] == "ASSIGNED"


def test_vendor_active_job_count_returns_to_one_after_cycle(api):
    """PRD §3.5: "On success the request's `vendor_id` is set, its
    `estimated_cost_cents` is computed (see below), and the vendor's
    `active_job_count` is increased by one, moving the request to `ASSIGNED`."

    The assign/unassign/assign loop leaves the vendor's active_job_count at 1.

    Design: Difficulty/non_linear_state_machine/service_triaged_assigned_triaged_cycle
    """
    _, vendor_id = _setup_reassigned_request(api)
    vendor = validate_success(api.get_vendor(vendor_id, fx.PM))
    assert vendor["active_job_count"] == 1
