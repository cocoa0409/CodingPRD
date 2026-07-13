"""Ticket creation, triage scoring / banding, and triage state guards."""
from test_helpers import (
    validate_success, validate_error,
    create_ticket_payload,
)
from test_helpers.fixtures import (
    new_intersection, new_device, new_ticket, triage,
)


def test_priority_score_capped_at_100(api, dispatcher_headers):
    """PRD §3.2: "These four contributions are summed and then capped at 100, so
    `priority_score` is the smaller of 100 and the raw total."
    PRD §3.2: "The source contributes 10 points for `SRC_311`, 15 for `DETECTOR`,
    and 30 for `KNOCKDOWN`. The device's criticality contributes 40 points for
    `CRITICAL`, 20 for `STANDARD`, and 10 for `LOW`. The reported severity
    contributes 8 points per severity level (so its 1-to-5 range yields 8 to 40
    points). A reported hazard adds a further 25 points, and nothing when the
    hazard flag is false."

    Design: Difficulty/combinatorial_formula/ticket_priority_score_capped_tiered_hazard_override
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_CONTROLLER",
                        criticality="CRITICAL", model="C1", replacement_cost=5000.00)
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=4,
                        description="dark signal", hazard_flag=True)
    # Raw = 10 + 40 + 32 + 25 = 107, capped to 100.
    triaged = triage(ticket["id"])
    assert triaged["priority_score"] == 100, f"expected capped 100, got {triaged['priority_score']}"


def test_priority_band_p1_at_score_ceiling(api, dispatcher_headers):
    """PRD §3.2: "If the score is at least 80 — or if the ticket carries a hazard
    and the device is `CRITICAL`, which forces the top band regardless of the
    numeric score — the band is `P1`."

    Design: Difficulty/combinatorial_formula/ticket_priority_score_capped_tiered_hazard_override
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_CONTROLLER",
                        criticality="CRITICAL", model="C1", replacement_cost=5000.00)
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=4,
                        description="dark signal", hazard_flag=True)
    triaged = triage(ticket["id"])
    assert triaged["priority_band"] == "P1", f"expected P1, got {triaged['priority_band']}"


def test_priority_band_p3_midrange(api, dispatcher_headers):
    """PRD §3.2: "The source contributes 10 points for `SRC_311`, 15 for
    `DETECTOR`, and 30 for `KNOCKDOWN`. The device's criticality contributes 40
    points for `CRITICAL`, 20 for `STANDARD`, and 10 for `LOW`. The reported
    severity contributes 8 points per severity level (so its 1-to-5 range yields 8
    to 40 points). A reported hazard adds a further 25 points, and nothing when the
    hazard flag is false."
    PRD §3.2: "Otherwise a score of at least 60 is `P2`, a score of at least 35 is
    `P3`, and anything below 35 is `P4`."

    Design: Corner/calculations/priority_band_p3_midrange
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="DETECTOR", criticality="STANDARD",
                        model="D9", replacement_cost=400.00)
    ticket = new_ticket(device["id"], source="DETECTOR", reported_severity=2,
                        description="loop fault")
    # 15 + 20 + 16 + 0 = 51 -> P3.
    triaged = triage(ticket["id"])
    assert triaged["priority_score"] == 51, f"expected 51, got {triaged['priority_score']}"
    assert triaged["priority_band"] == "P3"


def test_new_ticket_initial_state_open(api, dispatcher_headers):
    """PRD §3.2: "A fresh ticket opens in `OPEN` status with `sla_response_status`
    of `PENDING`, and its `priority_score`, `priority_band`, `triaged_at`,
    `response_due`, and `resolution_due` all remain empty until triage runs."

    Design: Corner/state_machines/new_ticket_initial_state_open
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    res = api.create_ticket(
        create_ticket_payload(device_id=device["id"], source="DETECTOR",
                              reported_severity=2, description="x"),
        dispatcher_headers)
    ticket = validate_success(res, 201)
    assert ticket["status"] == "OPEN"
    assert ticket["sla_response_status"] == "PENDING"


def test_ticket_severity_out_of_range_rejected(api, dispatcher_headers):
    """PRD §3.2: "`reported_severity` must be an integer from 1 through 5
    inclusive; a value outside that range is an `ERR_VALIDATION` (422)."

    Design: Corner/entities/ticket_severity_out_of_range_rejected
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    res = api.create_ticket(
        create_ticket_payload(device_id=device["id"], source="SRC_311",
                              reported_severity=6, description="bad severity"),
        dispatcher_headers)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_triage_twice_rejected_invalid_state(api, dispatcher_headers):
    """PRD §3.2: "Triage is where a ticket is scored and its downstream cascade
    fires; it moves the ticket from `OPEN` to `TRIAGED`."
    PRD §2.9: "State — the target resource is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/triage_twice_idempotency_rejected
    """
    inter = new_intersection()
    device = new_device(inter["id"], device_type="SIGNAL_HEAD", criticality="STANDARD")
    ticket = new_ticket(device["id"], source="SRC_311", reported_severity=3, description="x")
    triage(ticket["id"])
    res = api.triage_ticket(ticket["id"], dispatcher_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    fetched = validate_success(api.get_ticket(ticket["id"], dispatcher_headers), 200)
    assert fetched["status"] == "TRIAGED"
