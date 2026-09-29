"""
Immediate consistency: the write's own reply and the reads that follow it already agree.

Every test builds its own world from scratch through declared endpoints — the harness
restarts the API with an empty database before each test — and sets the logical clock
explicitly whenever the scenario names an instant.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    SERVICE_COORDINATOR,
    arrive_call,
    assert_fields,
    assert_instant,
    assert_money,
    assert_two_decimals,
    build_fleet,
    dispatch_call,
    event_for_call,
    get_success_data,
    open_call,
    read_club,
    read_contract,
    read_equipment,
    read_event,
    read_technician,
    resolve_payload,
    set_clock,
    technician_headers,
)


def test_resolving_a_call_leaves_every_cascaded_number_readable_on_the_first_attempt(api):
    """
    The resolve reply and the event, machine, contract, technician and club reads that
    follow it agree immediately, with no retry and no convergence delay.

    PRD: "There is no deferred job and no eventual consistency: by the time a response is
    returned, every counter the request touched already reflects the new reality, and any
    row that moved carries a refreshed `updated_at` and an advanced `version`."

    Design: Corner/consistency_model/the_write_response_and_the_next_read_already_agree
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        club_kwargs={"name": "Northside Fitness", "region_code": "NW"},
        serials=["SN-IM-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        technicians=[{"full_name": "Dana Reyes"}],
    )
    club_id = fleet["club_id"]
    contract_id = fleet["contract_id"]
    e1 = fleet["equipment_ids"][0]
    t1 = fleet["technician_ids"][0]

    # The response window is frozen on creation and settled at arrival, in those replies.
    call = open_call(api, contract_id, e1, severity="MAJOR", symptom_code="BELT_NOISE")
    assert_fields(call, status="OPEN", sla_target_minutes=120)
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", t1)
    assert read_technician(api, t1)["committed_minutes"] == 120

    set_clock(api, "2026-08-15T08:30:00Z")
    arrived = arrive_call(api, call["id"], t1)
    assert_fields(arrived, status="ON_SITE", response_minutes=30, sla_met=True)
    assert_instant(arrived["arrived_at"], "2026-08-15T08:30:00Z", "arrived_at")

    # The write's own body already carries the resolved state and the settled verdict.
    set_clock(api, "2026-08-15T14:00:00Z")
    written = get_success_data(
        api.resolve_service_call(
            call["id"], resolve_payload("BELT_TENSIONED"), technician_headers(t1)
        )
    )
    assert_fields(
        written,
        status="RESOLVED",
        response_minutes=30,
        sla_met=True,
        resolution_code="BELT_TENSIONED",
    )
    assert_instant(written["resolved_at"], "2026-08-15T14:00:00Z", "resolved_at")

    # First read of the event the resolution closed: every computed figure is present.
    event = event_for_call(api, call["id"])
    assert_fields(event, status="CLOSED", downtime_minutes=360, period_key="2026-08")
    assert_money(event["provisional_credit_cents"], 4800, "provisional credit")
    assert_instant(event["ended_at"], "2026-08-15T14:00:00Z", "ended_at")

    # First read of the machine: the cascade into the unit was already durable.
    unit = read_equipment(api, e1)
    assert_fields(unit, lifecycle_status="IN_SERVICE", downtime_minutes_ytd=360)

    # First read of the contract: provisional credit is visible, accrual still waits.
    contract = read_contract(api, contract_id)
    assert_money(contract["credit_provisional_cents"], 4800, "provisional roll-up")
    assert_money(contract["credit_accrued_cents"], 0, "accrued before reconciliation")

    # First read of the technician: the same write released the reservation.
    technician = read_technician(api, t1)
    assert_fields(technician, committed_minutes=0, duty_status="ON_DUTY")

    # First read of the club: its lockout counter was recomputed in the same request.
    assert_fields(read_club(api, club_id), open_safety_lockout_count=0)

    # No value moved between two consecutive reads, so nothing converged after the fact.
    second_event = read_event(api, event["id"])
    assert_fields(
        second_event, id=event["id"], status="CLOSED", downtime_minutes=360
    )
    assert_money(
        second_event["provisional_credit_cents"], 4800, "provisional credit re-read"
    )
    second_unit = read_equipment(api, e1)
    assert_fields(second_unit, lifecycle_status="IN_SERVICE", downtime_minutes_ytd=360)
    assert_two_decimals(second_unit["health_score"], unit["health_score"], "health_score")
    assert second_unit["health_score_variant"] == unit["health_score_variant"]
    assert second_unit["replacement_recommended"] == unit["replacement_recommended"]
    second_contract = read_contract(api, contract_id)
    assert_money(
        second_contract["credit_provisional_cents"], 4800, "provisional roll-up re-read"
    )
    assert_fields(
        second_contract,
        version=contract["version"],
        replacement_candidate_count=contract["replacement_candidate_count"],
        fleet_renewal_risk=contract["fleet_renewal_risk"],
    )
    assert_instant(
        second_contract["updated_at"], contract["updated_at"], "contract updated_at"
    )
    assert read_technician(api, t1)["committed_minutes"] == 0
    assert (
        get_success_data(api.get_service_call(call["id"], SERVICE_COORDINATOR))["status"]
        == "RESOLVED"
    )
    assert (
        get_success_data(api.get_service_call(call["id"], CONTRACT_ADMIN))[
            "response_minutes"
        ]
        == 30
    )
