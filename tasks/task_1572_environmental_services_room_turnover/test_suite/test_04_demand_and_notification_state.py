"""PlacementDemand and BedReadyNotification state machine claims."""
from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    assert_instant_equal,
    create_placement_demand_payload,
    create_unit_payload,
    get_success_data,
    set_clock,
    setup_ready_bed_with_match,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_placement_demand_matched_and_terminal_states_reject_writes(api):
    """PRD §3.2: "Regrading anything but an `OPEN` demand is rejected with
    `ERR_DEMAND_NOT_OPEN`. A demand may also be **cancelled** from `OPEN` or
    `MATCHED`; cancelling a demand in any other state is likewise
    `ERR_DEMAND_NOT_OPEN`."
    PRD §3.7: "When a demand is `MATCHED` to the bed, admission fulfills it —
    the demand becomes `FULFILLED` with `fulfilled_at` stamped."

    Design: Corner/state_machines/placement_demand_matched_and_terminal_states_reject_writes
    """
    ctx = setup_ready_bed_with_match()
    demand = ctx["demand"]
    assert demand["status"] == "MATCHED"

    r_regrade_matched = api.regrade_placement_demand(
        demand["id"], {"urgency_tier": "STAT"}, COORDINATOR
    )
    validate_error(r_regrade_matched, ApiErrorId.ERR_DEMAND_NOT_OPEN)

    # Admit fulfills the matched demand.
    get_success_data(api.admit_bed(ctx["bed"]["id"], COORDINATOR))
    fulfilled = validate_success(api.get_placement_demand(demand["id"], ANY))
    assert fulfilled["status"] == "FULFILLED"
    assert_instant_equal(fulfilled["fulfilled_at"], "2026-08-01T08:45:00Z")

    r_cancel_f = api.cancel_placement_demand(demand["id"], COORDINATOR)
    validate_error(r_cancel_f, ApiErrorId.ERR_DEMAND_NOT_OPEN)
    r_regrade_f = api.regrade_placement_demand(
        demand["id"], {"urgency_tier": "STANDARD"}, COORDINATOR
    )
    validate_error(r_regrade_f, ApiErrorId.ERR_DEMAND_NOT_OPEN)

    # A second demand cancelled -> CANCELLED, then both writes rejected.
    d2 = get_success_data(
        api.create_placement_demand(
            create_placement_demand_payload(
                unit_id=ctx["unit"]["id"], urgency_tier="STANDARD"
            ),
            COORDINATOR,
        )
    )
    get_success_data(api.cancel_placement_demand(d2["id"], COORDINATOR))
    r_cancel_c = api.cancel_placement_demand(d2["id"], COORDINATOR)
    validate_error(r_cancel_c, ApiErrorId.ERR_DEMAND_NOT_OPEN)
    r_regrade_c = api.regrade_placement_demand(
        d2["id"], {"urgency_tier": "STAT"}, COORDINATOR
    )
    validate_error(r_regrade_c, ApiErrorId.ERR_DEMAND_NOT_OPEN)

    final = validate_success(api.get_placement_demand(demand["id"], ANY))
    assert final["urgency_tier"] == "URGENT"


def test_placement_demand_expiry_requires_needed_by_strictly_past(api):
    """PRD §3.2: "An `OPEN` demand whose `needed_by` falls strictly before the
    current clock is expired by the next ops-run; at exact equality with the
    clock the demand stays `OPEN`."

    Design: Corner/state_machines/placement_demand_expiry_requires_needed_by_strictly_past
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    demand = get_success_data(
        api.create_placement_demand(
            create_placement_demand_payload(
                unit_id=unit["id"], needed_by="2026-08-01T09:00:00Z"
            ),
            COORDINATOR,
        )
    )

    set_clock("2026-08-01T09:00:00Z")
    get_success_data(api.run_ops_run(unit["id"], ADMIN))
    at_eq = validate_success(api.get_placement_demand(demand["id"], ANY))
    assert at_eq["status"] == "OPEN"

    set_clock("2026-08-01T09:01:00Z")
    get_success_data(api.run_ops_run(unit["id"], ADMIN))
    after = validate_success(api.get_placement_demand(demand["id"], ANY))
    assert after["status"] == "EXPIRED"

    unit_after = validate_success(api.get_unit(unit["id"], ANY))
    assert unit_after["ops_run_index"] == 2


def test_notification_acknowledge_requires_sent_state(api):
    """PRD §3.7: "A coordinator may **acknowledge** it — only a `SENT`
    notification can be acknowledged (`ERR_NOTIFICATION_NOT_SENT` otherwise) —
    stamping `acknowledged_at`."

    Design: Corner/state_machines/notification_acknowledge_requires_sent_state
    """
    ctx = setup_ready_bed_with_match()
    notif = ctx["notification"]
    assert notif is not None and notif["status"] == "SENT"

    acked = validate_success(
        api.acknowledge_bed_ready_notification(notif["id"], COORDINATOR)
    )
    assert acked["status"] == "ACKNOWLEDGED"
    assert_instant_equal(acked["acknowledged_at"], "2026-08-01T08:45:00Z")

    r_again = api.acknowledge_bed_ready_notification(notif["id"], COORDINATOR)
    validate_error(r_again, ApiErrorId.ERR_NOTIFICATION_NOT_SENT)

    demand = validate_success(api.get_placement_demand(ctx["demand"]["id"], ANY))
    assert demand["status"] == "MATCHED"


def test_notification_ops_run_expiry_boundary_and_rematch(api):
    """PRD §3.7: "And it **expires** at an ops-run once the clock has moved
    strictly more than 60 minutes past `sent_at`; at exact equality it stays
    `SENT`. Expiry moves the matched demand back to `OPEN` with
    `matched_bed_id` cleared, and the bed remains `READY`, eligible for the
    same ops-run's rematch pass (§3.9)."

    Design: Corner/state_machines/notification_ops_run_expiry_boundary_and_rematch
    """
    ctx = setup_ready_bed_with_match()
    n1 = ctx["notification"]
    assert_instant_equal(n1["sent_at"], "2026-08-01T08:45:00Z")

    # Exact equality: 08:45 + 60min == 09:45 -> stays SENT.
    set_clock("2026-08-01T09:45:00Z")
    get_success_data(api.run_ops_run(ctx["unit"]["id"], ADMIN))
    n1_at_eq = validate_success(api.get_bed_ready_notification(n1["id"], ANY))
    assert n1_at_eq["status"] == "SENT"

    # One minute past -> expires; the same run's rematch re-matches the bed.
    set_clock("2026-08-01T09:46:00Z")
    get_success_data(api.run_ops_run(ctx["unit"]["id"], ADMIN))
    n1_after = validate_success(api.get_bed_ready_notification(n1["id"], ANY))
    assert n1_after["status"] == "EXPIRED"

    demand = validate_success(api.get_placement_demand(ctx["demand"]["id"], ANY))
    assert demand["status"] == "MATCHED"
    assert demand["matched_bed_id"] == ctx["bed"]["id"]

    sent, _meta = __import__("test_helpers").validate_paginated(
        api.list_bed_ready_notifications(
            ANY, params={"bed_id": ctx["bed"]["id"], "status": "SENT"}
        )
    )
    assert len(sent) == 1
    assert sent[0]["id"] != n1["id"]

    bed = validate_success(api.get_bed(ctx["bed"]["id"], ANY))
    assert bed["bed_status"] == "READY"
