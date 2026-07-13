"""Role-based access control: peer-role denial and FieldTech crew ownership."""
from test_helpers import validate_success, validate_error, make_fieldtech_headers
from test_helpers.fixtures import (
    new_intersection, new_device, new_crew, new_ticket, new_timing_change_request,
    get_timing_change_request, get_ticket, setup_dispatched_work_order,
)


def test_dispatcher_cannot_approve_timing_change(api, dispatcher_headers, traffic_engineer_headers):
    """PRD §3.6: "From `UNDER_REVIEW` the request forks three ways under the traffic
    engineer. Approval moves it to the terminal `APPROVED` state and is likewise
    blocked while the intersection is in `EMERGENCY` posture."
    PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/dispatcher_cannot_approve_timing_change
    """
    inter = new_intersection()
    tcr = new_timing_change_request(inter["id"], proposed_cycle_length_sec=90,
                                    proposed_offset_sec=5, rationale="x")
    validate_success(api.start_review_timing_change_request(tcr["id"], traffic_engineer_headers), 200)
    res = api.approve_timing_change_request(tcr["id"], dispatcher_headers)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert get_timing_change_request(tcr["id"])["status"] == "UNDER_REVIEW"


def test_fieldtech_cannot_complete_other_crew_work(api, dispatcher_headers):
    """PRD §2.1: "A field technician may only complete a work order whose `crew_id`
    equals their `X-User-ID`; a mismatch is an `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/fieldtech_cannot_complete_other_crew_work
    """
    ctx = setup_dispatched_work_order(work_type="REPAIR", estimated_labor_hours=1.0,
                                      with_ticket=False)
    crew_b = new_crew(name="Crew B", specialty="SIGNAL", labor_capacity_hours=8.0)
    res = api.complete_work_order(ctx["wo_id"], {"actual_labor_hours": 1.0},
                                  make_fieldtech_headers(crew_b["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    fetched = validate_success(api.get_work_order(ctx["wo_id"], dispatcher_headers), 200)
    assert fetched["status"] == "DISPATCHED"


def test_utility_coordinator_cannot_triage_ticket(api, dispatcher_headers, utility_coordinator_headers):
    """PRD §2.1: "`Dispatcher` owns the ticket and work-order pipelines and may
    submit and resubmit timing change requests."
    PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/utility_coordinator_cannot_triage_ticket
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=3, description="x")
    res = api.triage_ticket(ticket["id"], utility_coordinator_headers)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert get_ticket(ticket["id"])["status"] == "OPEN"
