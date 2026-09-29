"""
Terminal states, replayed triggers and the ledger effects that follow them.

Every test in this module drives one FleetCare state machine to a boundary the PRD
pins exactly — a replayed trigger, a terminal contract or quote, an expiry instant, a
selective teardown cascade, a compensating waiver or a bounded parts cycle — and then
asserts both the row that moved and every row the cascade reached, including the
`version` each of them advanced to.

Money is asserted in integer cents and instants through ``assert_instant``, because the
PRD renders timestamps with exactly three fractional digits while a test spells the
instant it means.
"""

from test_helpers import (
    ERR_CALL_INVALID_STATE,
    ERR_CONTRACT_INVALID_STATE,
    ERR_PARTS_HOLD_LIMIT,
    ERR_QUOTE_EXPIRED,
    ERR_QUOTE_NOT_ISSUED,
    ERR_UNRESOLVED_PART_ORDER,
    ERR_VISIT_INVALID_STATE,
    arrive_call,
    assert_common_fields,
    assert_fields,
    assert_instant,
    assert_money,
    assert_null_fields,
    assert_part_inventory_identity,
    assert_parts_allowance_identity,
    assert_technician_capacity_identity,
    assert_two_decimals,
    assignment_for_visit,
    build_fleet,
    checklist_item,
    checklist_result_payload,
    dispatch_call,
    event_for_call,
    get_success_data,
    inspector_headers,
    new_club,
    new_contract,
    new_part,
    open_call,
    parts_hold_payload,
    place_hold,
    quote_decline_payload,
    read_call,
    read_contract,
    read_equipment,
    read_part,
    read_quote,
    read_technician,
    read_visit,
    record_usage,
    renewal_quote_payload,
    resolve_payload,
    rows_of,
    safety_doc_submit_payload,
    schedule_visit,
    set_clock,
    start_visit,
    suspend_payload,
    technician_headers,
    validate_error,
    waive_payload,
)

# One technician spec reused by the scenarios that need a single eligible engineer in
# the club's own region with the serviced model's category on their ticket.
TREADMILL_TECH_NORTH = {
    "full_name": "Dana Reyes",
    "region_code": "NW",
    "skill_categories": ["TREADMILL"],
}
SECOND_TREADMILL_TECH_NORTH = {
    "full_name": "Ravi Shah",
    "region_code": "NW",
    "skill_categories": ["TREADMILL"],
}
INSPECTOR_TECH_NORTH = {
    "full_name": "Omar Diaz",
    "region_code": "NW",
    "skill_categories": ["TREADMILL"],
    "is_safety_inspector": True,
}


# ─── Replaying a successful trigger ───────────────────────────────────────────


def test_replaying_activation_on_an_active_contract_leaves_the_version_at_two(api, admin):
    """
    Activation succeeds once; the replay is a contract state error and no version moves.

    PRD: "A contract lifecycle action must match the contract's `status`: activation
    requires `DRAFT`, suspension requires `ACTIVE`, reinstatement requires `SUSPENDED`,
    and renewal quoting requires `ACTIVE` or `RENEWAL_QUOTED`; otherwise
    `ERR_CONTRACT_INVALID_STATE` (409)."

    Design: Corner/state_machines/replaying_a_successful_trigger_is_rejected_on_the_second_attempt
    """
    set_clock(api, "2026-08-15T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    contract = new_contract(api, club["id"], annual_base_cents=140000)
    assert_fields(contract, status="DRAFT")
    assert_common_fields(contract, expected_version=1)

    activated = get_success_data(api.activate_contract(contract["id"], admin), 200)
    assert_fields(activated, status="ACTIVE")
    assert_common_fields(activated, expected_version=2)

    replay = api.activate_contract(contract["id"], admin)
    validate_error(replay, ERR_CONTRACT_INVALID_STATE, 409)

    after = read_contract(api, contract["id"])
    assert_fields(after, status="ACTIVE")
    assert_common_fields(after, expected_version=2)


def test_replaying_arrival_on_an_on_site_call_keeps_the_first_response_time(api):
    """
    A second arrival is refused and neither arrived_at nor response_minutes is re-stamped.

    PRD: "The assigned technician records arrival on a `DISPATCHED` call; anyone else is
    `ERR_TECHNICIAN_NOT_ASSIGNED` and any other status is `ERR_CALL_INVALID_STATE`."

    Design: Corner/state_machines/replaying_a_successful_trigger_is_rejected_on_the_second_attempt
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-ID-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    technician_id = fleet["technician_ids"][0]
    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)

    set_clock(api, "2026-08-15T08:45:00Z")
    arrived = arrive_call(api, call["id"], technician_id)
    assert_fields(arrived, status="ON_SITE", response_minutes=45, sla_met=True)
    assert_instant(arrived["arrived_at"], "2026-08-15T08:45:00Z", "arrived_at")
    assert_common_fields(arrived, expected_version=3)

    set_clock(api, "2026-08-15T09:30:00Z")
    replay = api.arrive_service_call(call["id"], technician_headers(technician_id))
    validate_error(replay, ERR_CALL_INVALID_STATE, 409)

    after = read_call(api, call["id"])
    assert_fields(after, status="ON_SITE", response_minutes=45, sla_met=True)
    assert_instant(after["arrived_at"], "2026-08-15T08:45:00Z", "arrived_at")
    assert_common_fields(after, expected_version=3)


def test_replaying_the_start_of_a_running_visit_does_not_restamp_started_at(api):
    """
    A second start is refused and the visit's assignment is confirmed exactly once.

    PRD: "A visit action must match `visit_status`: start requires `SCHEDULED`, checklist
    recording and completion require `IN_PROGRESS`, cancellation requires `SCHEDULED`,
    and marking missed requires `SCHEDULED` together with a logical clock at or after
    `window_end`; otherwise `ERR_VISIT_INVALID_STATE` (409)."

    Design: Corner/state_machines/replaying_a_successful_trigger_is_rejected_on_the_second_attempt
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T09:30:00Z",
        serials=["SN-ID-2"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[SECOND_TREADMILL_TECH_NORTH],
    )
    technician_id = fleet["technician_ids"][0]
    visit = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        "2026-08-15T12:00:00Z",
        "2026-08-15T13:30:00Z",
        technician_id,
    )

    started = start_visit(api, visit["id"], technician_id)
    assert_fields(started, visit_status="IN_PROGRESS")
    assert_instant(started["started_at"], "2026-08-15T09:30:00Z", "started_at")
    assert_common_fields(started, expected_version=2)

    replay = api.start_visit(visit["id"], technician_headers(technician_id))
    validate_error(replay, ERR_VISIT_INVALID_STATE, 409)

    after = read_visit(api, visit["id"])
    assert_fields(after, visit_status="IN_PROGRESS")
    assert_instant(after["started_at"], "2026-08-15T09:30:00Z", "started_at")
    assert_common_fields(after, expected_version=2)

    assignment = assignment_for_visit(api, visit["id"])
    assert_fields(assignment, status="CONFIRMED", planned_minutes=90)
    assert_common_fields(assignment, expected_version=2)
    technician = read_technician(api, technician_id)
    assert technician["committed_minutes"] == 90
    assert_technician_capacity_identity(technician, [assignment])


# ─── The renewed contract and the accepted quote are both terminal ────────────


def test_a_renewed_contract_refuses_suspension_and_a_freshly_versioned_requote(api, admin):
    """
    Both writes fail on the contract's terminal status, not on the concurrency token.

    PRD: "`RENEWED` and `EXPIRED` are both terminal: there is no further transition out
    of either, and no operational work of any kind is permitted against a contract in
    either state."

    Design: Corner/state_machines/renewed_contract_and_accepted_quote_are_both_locked_down
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T12:00:00Z",
        serials=["SN-TL-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
    )
    contract_id = fleet["contract_id"]
    assert_common_fields(fleet["contract"], expected_version=2)

    quote = get_success_data(
        api.create_renewal_quote(contract_id, renewal_quote_payload(2), admin), 201
    )
    accepted = get_success_data(api.accept_renewal_quote(quote["id"], fleet["manager"]), 200)
    assert_fields(accepted, status="ACCEPTED")

    renewed = read_contract(api, contract_id)
    assert_fields(renewed, status="RENEWED")
    # create 1, activate 2, quote 3, accept 4.
    assert_common_fields(renewed, expected_version=4)

    refused_suspend = api.suspend_contract(
        contract_id, suspend_payload(reason="TOO_LATE"), admin
    )
    validate_error(refused_suspend, ERR_CONTRACT_INVALID_STATE, 409)

    # The token presented here is the contract's live version, so the concurrency rung
    # passes and the state rung below it is what answers.
    refused_requote = api.create_renewal_quote(
        contract_id, renewal_quote_payload(renewed["version"]), admin
    )
    validate_error(refused_requote, ERR_CONTRACT_INVALID_STATE, 409)

    after = read_contract(api, contract_id)
    assert_fields(after, status="RENEWED")
    assert_null_fields(after, "suspension_reason")
    assert_common_fields(after, expected_version=4)


def test_replaying_the_accept_of_an_accepted_quote_answers_the_quote_state_error(api, admin):
    """
    A second acceptance is refused on the quote's own status and no new quote appears.

    PRD: "Both actions require the quote to be `ISSUED` and the contract to be
    `RENEWAL_QUOTED` (`ERR_QUOTE_NOT_ISSUED`), and both require the logical clock to be
    strictly before `expires_at` (`ERR_QUOTE_EXPIRED`); a decision landing exactly on
    `expires_at` is too late."

    Design: Corner/state_machines/renewed_contract_and_accepted_quote_are_both_locked_down
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T12:00:00Z",
        serials=["SN-TL-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
    )
    contract_id = fleet["contract_id"]
    quote = get_success_data(
        api.create_renewal_quote(contract_id, renewal_quote_payload(2), admin), 201
    )
    assert_common_fields(quote, expected_version=1)

    accepted = get_success_data(api.accept_renewal_quote(quote["id"], fleet["manager"]), 200)
    assert_fields(accepted, status="ACCEPTED")
    assert_common_fields(accepted, expected_version=2)

    replay = api.accept_renewal_quote(quote["id"], fleet["manager"])
    validate_error(replay, ERR_QUOTE_NOT_ISSUED, 409)

    after = read_quote(api, quote["id"])
    assert_fields(after, status="ACCEPTED")
    assert_common_fields(after, expected_version=2)

    quotes = rows_of(api.list_renewal_quotes(admin, contract_id=contract_id))
    assert len(quotes) == 1, f"expected exactly one quote on the contract, got {len(quotes)}"
    assert_fields(quotes[0], id=quote["id"], status="ACCEPTED")


# ─── The expiry instant is strict ─────────────────────────────────────────────


def test_quote_decisions_at_and_after_the_expiry_instant_are_refused(api, admin):
    """
    At expires_at and one second later both accept and decline answer the expiry error.

    PRD: "Both actions require the quote to be `ISSUED` and the contract to be
    `RENEWAL_QUOTED` (`ERR_QUOTE_NOT_ISSUED`), and both require the logical clock to be
    strictly before `expires_at` (`ERR_QUOTE_EXPIRED`); a decision landing exactly on
    `expires_at` is too late."

    Design: Corner/state_machines/quote_decisions_are_refused_at_exactly_the_expiry_instant
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T12:00:00Z",
        serials=["SN-QX-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
    )
    contract_id = fleet["contract_id"]
    quote = get_success_data(
        api.create_renewal_quote(contract_id, renewal_quote_payload(2), admin), 201
    )
    assert_instant(quote["issued_at"], "2026-08-15T12:00:00Z", "issued_at")
    # "expires_at is exactly 30 days later".
    assert_instant(quote["expires_at"], "2026-09-14T12:00:00Z", "expires_at")

    set_clock(api, "2026-09-14T12:00:00Z")
    refused_accept = api.accept_renewal_quote(quote["id"], fleet["manager"])
    validate_error(refused_accept, ERR_QUOTE_EXPIRED, 409)
    refused_decline = api.decline_renewal_quote(
        quote["id"], quote_decline_payload(reason="BUDGET"), fleet["manager"]
    )
    validate_error(refused_decline, ERR_QUOTE_EXPIRED, 409)

    set_clock(api, "2026-09-14T12:00:01Z")
    refused_later = api.accept_renewal_quote(quote["id"], fleet["manager"])
    validate_error(refused_later, ERR_QUOTE_EXPIRED, 409)

    unchanged = read_quote(api, quote["id"])
    assert_fields(unchanged, status="ISSUED")
    assert_null_fields(unchanged, "decline_reason")
    assert_common_fields(unchanged, expected_version=1)

    contract = read_contract(api, contract_id)
    assert_fields(contract, status="RENEWAL_QUOTED")
    # create 1, activate 2, quote 3 — no rejected decision advanced it.
    assert_common_fields(contract, expected_version=3)


def test_a_quote_accepted_one_second_before_expiry_still_renews_the_contract(api, admin):
    """
    One second inside the validity window the acceptance succeeds and the term renews.

    PRD: "Acceptance sets the quote's `status` to `ACCEPTED`, moves the contract to
    `RENEWED`, and advances `version` — and does nothing else."

    Design: Corner/state_machines/quote_decisions_are_refused_at_exactly_the_expiry_instant
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T12:00:00Z",
        serials=["SN-QX-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
    )
    contract_id = fleet["contract_id"]
    quote = get_success_data(
        api.create_renewal_quote(contract_id, renewal_quote_payload(2), admin), 201
    )
    assert_instant(quote["expires_at"], "2026-09-14T12:00:00Z", "expires_at")

    set_clock(api, "2026-09-14T11:59:59Z")
    accepted = get_success_data(api.accept_renewal_quote(quote["id"], fleet["manager"]), 200)
    assert_fields(accepted, status="ACCEPTED")
    assert_common_fields(accepted, expected_version=2)

    contract = read_contract(api, contract_id)
    assert_fields(contract, status="RENEWED")
    assert_common_fields(contract, expected_version=4)


# ─── Suspension tears down only the forward schedule ──────────────────────────


def test_suspension_cancels_the_scheduled_visit_and_leaves_the_running_one_alone(api, admin):
    """
    The teardown reaches the scheduled visit, its reservation and its technician only.

    PRD: "First, every preventive visit on this contract whose `visit_status` is
    `SCHEDULED` moves to `CANCELLED` with its `cancellation_reason` set to the literal
    string `CONTRACT_SUSPENDED`; visits already `IN_PROGRESS`, `COMPLETED`, `MISSED` or
    `CANCELLED` are left untouched."

    Design: Corner/state_machines/suspension_cascades_only_into_still_scheduled_visits
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T07:00:00Z",
        serials=["SN-CS-1", "SN-CS-2"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH, SECOND_TREADMILL_TECH_NORTH],
    )
    contract_id = fleet["contract_id"]
    first_technician, second_technician = fleet["technician_ids"]
    scheduled = schedule_visit(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        "2026-08-15T08:00:00Z",
        "2026-08-15T09:30:00Z",
        first_technician,
    )
    running = schedule_visit(
        api,
        contract_id,
        fleet["equipment_ids"][1],
        "2026-08-15T12:00:00Z",
        "2026-08-15T13:30:00Z",
        second_technician,
    )

    set_clock(api, "2026-08-15T12:00:00Z")
    start_visit(api, running["id"], second_technician)

    set_clock(api, "2026-08-15T12:15:00Z")
    suspended = get_success_data(
        api.suspend_contract(contract_id, suspend_payload(reason="NON_PAYMENT"), admin), 200
    )
    assert_fields(suspended, status="SUSPENDED", suspension_reason="NON_PAYMENT")
    # create 1, activate 2, suspend 3 — booking and starting visits never touched it.
    assert_common_fields(suspended, expected_version=3)

    cancelled = read_visit(api, scheduled["id"])
    assert_fields(
        cancelled, visit_status="CANCELLED", cancellation_reason="CONTRACT_SUSPENDED"
    )
    assert_common_fields(cancelled, expected_version=2)
    released = assignment_for_visit(api, scheduled["id"])
    assert_fields(released, status="RELEASED", release_reason="CONTRACT_SUSPENDED")
    assert_common_fields(released, expected_version=2)
    freed = read_technician(api, first_technician)
    assert freed["committed_minutes"] == 0
    assert_technician_capacity_identity(freed, [released])

    untouched = read_visit(api, running["id"])
    assert_fields(untouched, visit_status="IN_PROGRESS")
    assert_null_fields(untouched, "cancellation_reason")
    assert_instant(untouched["started_at"], "2026-08-15T12:00:00Z", "started_at")
    assert_common_fields(untouched, expected_version=2)
    kept = assignment_for_visit(api, running["id"])
    assert_fields(kept, status="CONFIRMED", planned_minutes=90)
    assert_common_fields(kept, expected_version=2)
    still_committed = read_technician(api, second_technician)
    assert still_committed["committed_minutes"] == 90
    assert_technician_capacity_identity(still_committed, [kept])

    # A cancelled visit is excluded from compliance permanently and the running one is
    # not yet history, so the percentage is still the empty-history value.
    assert_fields(suspended, pm_visits_completed_count=0, pm_visits_missed_count=0)
    assert_two_decimals(suspended["pm_compliance_pct"], 100.00)


# ─── A loaner swap caps the downtime clock ────────────────────────────────────


def test_installing_a_loaner_swap_mitigates_the_open_event_and_costs_nothing(api, planner):
    """
    The zero-priced loaner allocation stamps mitigated_at on the still-open event.

    PRD: "An installed order whose `source` is `LOANER_SWAP` does one thing more: it sets
    the machine's `loaner_active` to `true` and stamps `mitigated_at` on the call's open
    `DowntimeEvent` from the logical clock."

    Design: Corner/state_machines/loaner_swap_install_stops_the_downtime_clock_on_a_foreign_row
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-LN-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    technician_id = fleet["technician_ids"][0]
    part = new_part(
        api,
        fleet["model_id"],
        part_number="DECK-ASSY",
        category="STRUCTURAL",
        unit_price_cents=60000,
        initial_on_hand_qty=0,
        initial_refurb_qty=2,
    )
    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="DECK_CRACKED",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)
    arrive_call(api, call["id"], technician_id)
    place_hold(api, call["id"], technician_id, part["id"], qty=1, source="LOANER_SWAP")

    orders = rows_of(api.list_part_orders(planner, service_call_id=call["id"]))
    assert len(orders) == 1, f"expected exactly one part order, got {len(orders)}"
    order = orders[0]
    assert_fields(order, status="ALLOCATED", source="LOANER_SWAP", qty=1)
    # "A loaner swap therefore always produces a list_total_cents of exactly 0."
    assert_money(order["list_total_cents"], 0, "list_total_cents")
    assert_money(order["allowance_draw_cents"], 0, "allowance_draw_cents")
    assert_money(order["club_billable_cents"], 0, "club_billable_cents")

    set_clock(api, "2026-08-15T12:00:00Z")
    installed = get_success_data(
        api.install_part_order(order["id"], technician_headers(technician_id)), 200
    )
    assert_fields(installed, status="INSTALLED")
    assert_instant(installed["installed_at"], "2026-08-15T12:00:00Z", "installed_at")
    assert_common_fields(installed, expected_version=2)

    machine = read_equipment(api, fleet["equipment_ids"][0])
    assert_fields(machine, loaner_active=True, lifecycle_status="DOWN")
    # create 1, the call put it DOWN 2, the loaner install 3.
    assert_common_fields(machine, expected_version=3)

    event = event_for_call(api, call["id"])
    assert_fields(event, status="OPEN")
    assert_instant(event["mitigated_at"], "2026-08-15T12:00:00Z", "mitigated_at")
    assert_common_fields(event, expected_version=2)

    # Installation consumes the allocation without restoring the bucket it came from.
    after_part = read_part(api, part["id"])
    assert_fields(after_part, on_hand_qty=0, refurb_on_hand_qty=1, allocated_qty=0)
    assert_part_inventory_identity(after_part, [installed])

    contract = read_contract(api, fleet["contract_id"])
    assert_money(contract["parts_allowance_remaining_cents"], 500000, "allowance remaining")
    assert_parts_allowance_identity(contract, [installed])


def test_the_credit_stops_at_the_loaner_instant_not_at_the_resolution_instant(api):
    """
    Closing the event measures every span against mitigated_at, two hours short of ended_at.

    PRD: "Then `effective_end_at` is derived: it is `mitigated_at` when a loaner swap set
    that field (§3.7), and `ended_at` otherwise."

    Design: Corner/state_machines/loaner_swap_install_stops_the_downtime_clock_on_a_foreign_row
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-LN-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    technician_id = fleet["technician_ids"][0]
    equipment_id = fleet["equipment_ids"][0]
    part = new_part(
        api,
        fleet["model_id"],
        part_number="DECK-ASSY",
        category="STRUCTURAL",
        unit_price_cents=60000,
        initial_on_hand_qty=0,
        initial_refurb_qty=2,
    )
    call = open_call(
        api,
        fleet["contract_id"],
        equipment_id,
        severity="MAJOR",
        symptom_code="DECK_CRACKED",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)
    arrive_call(api, call["id"], technician_id)
    place_hold(api, call["id"], technician_id, part["id"], qty=1, source="LOANER_SWAP")
    order = rows_of(api.list_part_orders(technician_headers(technician_id),
                                         service_call_id=call["id"]))[0]

    set_clock(api, "2026-08-15T12:00:00Z")
    get_success_data(
        api.install_part_order(order["id"], technician_headers(technician_id)), 200
    )
    get_success_data(
        api.resume_service_call(call["id"], technician_headers(technician_id)), 200
    )

    set_clock(api, "2026-08-15T14:00:00Z")
    resolved = get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code="DECK_REPLACED"),
            technician_headers(technician_id),
        ),
        200,
    )
    assert_fields(resolved, status="RESOLVED")

    event = event_for_call(api, call["id"])
    assert_fields(event, status="CLOSED", period_key="2026-08")
    assert_instant(event["started_at"], "2026-08-15T08:00:00Z", "started_at")
    assert_instant(event["ended_at"], "2026-08-15T14:00:00Z", "ended_at")
    assert_instant(event["effective_end_at"], "2026-08-15T12:00:00Z", "effective_end_at")
    # 08:00 to 12:00, not 08:00 to 14:00 — the loaner truncated the billable outage.
    assert event["downtime_minutes"] == 240
    assert event["operating_downtime_minutes"] == 240
    # GOLD forgives 180 minutes and pays 1600 cents an hour: max(0, 240 - 180) / 60 * 1600.
    assert_money(event["provisional_credit_cents"], 1600, "provisional_credit_cents")

    machine = read_equipment(api, equipment_id)
    assert_fields(machine, lifecycle_status="IN_SERVICE")
    assert machine["downtime_minutes_ytd"] == 240

    contract = read_contract(api, fleet["contract_id"])
    assert_money(contract["credit_provisional_cents"], 1600, "credit_provisional_cents")


# ─── Waiving a closed event reverses the closure's arithmetic ──────────────────


def test_waiving_a_closed_event_takes_the_provisional_credit_back_off_the_contract(api, admin):
    """
    The ledger returns to its pre-closure state while the event keeps its own figures.

    PRD: "From `CLOSED`, the closure's arithmetic must be unwound: the contract's
    `credit_provisional_cents` falls by the event's `provisional_credit_cents` and the
    machine's `downtime_minutes_ytd` falls by the event's `downtime_minutes`, restoring
    both to their pre-closure values, after which `health_score`, `health_score_variant`
    and `replacement_recommended` are recomputed and the contract's
    `replacement_candidate_count` and `fleet_renewal_risk` re-derived."

    Design: Corner/state_machines/waiving_a_closed_event_reverses_every_number_it_posted
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-WV-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    contract_id = fleet["contract_id"]
    technician_id = fleet["technician_ids"][0]
    call = open_call(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)
    arrive_call(api, call["id"], technician_id)

    set_clock(api, "2026-08-15T14:00:00Z")
    get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code="BELT_TENSIONED"),
            technician_headers(technician_id),
        ),
        200,
    )
    closed = event_for_call(api, call["id"])
    assert_fields(closed, status="CLOSED")
    assert closed["downtime_minutes"] == 360
    # max(0, 360 - 180) / 60 * 1600 on a GOLD contract.
    assert_money(closed["provisional_credit_cents"], 4800, "provisional_credit_cents")

    before = get_success_data(api.get_credit_summary(contract_id, admin), 200)
    assert_money(before["credit_provisional_cents"], 4800, "summary provisional")
    assert_money(before["credit_accrued_cents"], 0, "summary accrued")
    assert_money(before["credit_forgone_cents"], 0, "summary forgone")
    # round_half_up(140000 * 0.15), pinned at contract creation.
    assert_money(before["credit_cap_cents"], 21000, "summary cap")
    assert_fields(before, open_event_count=0, closed_event_count=1, reconciled_event_count=0)

    waived = get_success_data(
        api.waive_downtime_event(
            closed["id"], waive_payload(waive_reason="GOODWILL_GESTURE"), admin
        ),
        200,
    )
    assert_fields(waived, status="WAIVED", waive_reason="GOODWILL_GESTURE")
    # created 1, closed by the resolution 2, waived 3.
    assert_common_fields(waived, expected_version=3)
    # "The event's own computed figures are left on the row in every branch."
    assert waived["downtime_minutes"] == 360
    assert_money(waived["provisional_credit_cents"], 4800, "provisional_credit_cents")

    after = get_success_data(api.get_credit_summary(contract_id, admin), 200)
    assert_money(after["credit_provisional_cents"], 0, "summary provisional")
    assert_money(after["credit_accrued_cents"], 0, "summary accrued")
    assert_money(after["credit_forgone_cents"], 0, "summary forgone")
    assert_fields(after, open_event_count=0, closed_event_count=0, reconciled_event_count=0)

    contract = read_contract(api, contract_id)
    assert_money(contract["credit_provisional_cents"], 0, "credit_provisional_cents")
    assert_money(contract["credit_accrued_cents"], 0, "credit_accrued_cents")
    assert_money(contract["credit_forgone_cents"], 0, "credit_forgone_cents")


def test_waiving_a_closed_event_rewinds_the_machine_and_the_fleet_risk(api, admin):
    """
    Year-to-date downtime returns to zero and the condition chain is recomputed from it.

    PRD: "The same chain runs in reverse when a downtime event is waived, and a shorter
    version of it — starting at `support_status` instead of at `downtime_minutes_ytd` —
    runs when a critical spare is declared end-of-support."

    Design: Corner/state_machines/waiving_a_closed_event_reverses_every_number_it_posted
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-WV-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    contract_id = fleet["contract_id"]
    equipment_id = fleet["equipment_ids"][0]
    technician_id = fleet["technician_ids"][0]
    call = open_call(
        api,
        contract_id,
        equipment_id,
        severity="MAJOR",
        symptom_code="BELT_NOISE",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)
    arrive_call(api, call["id"], technician_id)

    set_clock(api, "2026-08-15T14:00:00Z")
    get_success_data(
        api.resolve_service_call(
            call["id"],
            resolve_payload(resolution_code="BELT_TENSIONED"),
            technician_headers(technician_id),
        ),
        200,
    )
    posted = read_equipment(api, equipment_id)
    assert posted["downtime_minutes_ytd"] == 360

    event = event_for_call(api, call["id"])
    get_success_data(
        api.waive_downtime_event(
            event["id"], waive_payload(waive_reason="DATA_QUALITY"), admin
        ),
        200,
    )

    machine = read_equipment(api, equipment_id)
    assert machine["downtime_minutes_ytd"] == 0
    # One resolved call is fewer than three, so the usage-based variant still applies:
    # 100 - (100 * 500 / 20000) - (2 * 2) with an install date of 2024-03-01.
    assert_fields(
        machine, health_score_variant="USAGE_BASED", replacement_recommended=False
    )
    assert_two_decimals(machine["health_score"], 93.50)

    contract = read_contract(api, contract_id)
    assert_fields(contract, replacement_candidate_count=0, fleet_renewal_risk="LOW")


# ─── One order split across the allowance and the club's invoice ──────────────


def test_a_covered_order_larger_than_the_allowance_splits_across_both_buckets(api, planner):
    """
    The allowance absorbs what it can and the club is billed only the shortfall.

    PRD: "The allowance bucket fills first and the club is billed only what the allowance
    could not absorb, which means a partly exhausted allowance splits one order across
    both buckets — a covered order of 5,000 cents against a remaining allowance of 1,800
    cents draws 1,800 and bills the club 3,200."

    Design: Corner/state_machines/a_partly_funded_parts_draw_splits_across_allowance_and_club_billing
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-SP-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={
            "annual_base_cents": 140000,
            "initial_parts_allowance_cents": 10000,
        },
        technicians=[TREADMILL_TECH_NORTH],
    )
    contract_id = fleet["contract_id"]
    technician_id = fleet["technician_ids"][0]
    part = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=5,
    )
    call = open_call(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_WORN",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)
    arrive_call(api, call["id"], technician_id)
    place_hold(api, call["id"], technician_id, part["id"], qty=2, source="NEW")

    orders = rows_of(api.list_part_orders(planner, service_call_id=call["id"]))
    assert len(orders) == 1, f"expected exactly one part order, got {len(orders)}"
    order = orders[0]
    assert_fields(order, status="ALLOCATED", source="NEW", qty=2)
    # 8,000 a unit rounded before the multiply, so 16,000 list against 10,000 remaining.
    assert_money(order["list_total_cents"], 16000, "list_total_cents")
    assert_money(order["allowance_draw_cents"], 10000, "allowance_draw_cents")
    assert_money(order["club_billable_cents"], 6000, "club_billable_cents")
    # "The two buckets always sum to list_total_cents."
    assert order["allowance_draw_cents"] + order["club_billable_cents"] == (
        order["list_total_cents"]
    )
    assert_common_fields(order, expected_version=1)

    contract = read_contract(api, contract_id)
    assert_money(contract["parts_allowance_total_cents"], 10000, "allowance total")
    assert_money(contract["parts_allowance_remaining_cents"], 0, "allowance remaining")
    assert_parts_allowance_identity(contract, orders)

    after_part = read_part(api, part["id"])
    assert_fields(after_part, on_hand_qty=3, allocated_qty=2)
    assert_part_inventory_identity(after_part, orders)

    held = read_call(api, call["id"])
    assert_fields(held, status="PARTS_HOLD", parts_hold_count=1)


# ─── End-of-support reaches the fleet only through a critical spare ───────────


def test_end_of_support_on_a_non_critical_part_changes_nothing_but_its_own_row(api, planner):
    """
    The part goes obsolete with no refurbished stock and both covered units stay supported.

    PRD: "A part with `is_critical_spare` set to `false` changes nothing but its own row,
    however dramatic its declaration — the company's position is that a fleet is only
    stranded by the loss of a part it cannot run without."

    Design: Corner/state_machines/end_of_support_touches_the_fleet_only_for_a_critical_spare
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-EO-1", "SN-EO-2"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
    )
    trim = new_part(
        api,
        fleet["model_id"],
        part_number="CUP-HOLDER",
        category="CONSUMABLE",
        unit_price_cents=1500,
        is_critical_spare=False,
    )
    controller = new_part(
        api,
        fleet["model_id"],
        part_number="MOTOR-CTRL",
        category="ELECTRONIC",
        unit_price_cents=90000,
        is_critical_spare=True,
        initial_refurb_qty=1,
    )

    declared = get_success_data(api.declare_end_of_support(trim["id"], planner), 200)
    # No refurbished stock survives the declaration, so it lands terminally.
    assert_fields(declared, lifecycle_status="OBSOLETE", refurb_on_hand_qty=0)
    assert_instant(declared["eos_declared_at"], "2026-08-15T08:00:00Z", "eos_declared_at")
    assert_common_fields(declared, expected_version=2)

    untouched_part = read_part(api, controller["id"])
    assert_fields(untouched_part, lifecycle_status="ACTIVE")
    assert_null_fields(untouched_part, "eos_declared_at")
    assert_common_fields(untouched_part, expected_version=1)

    for equipment_id in fleet["equipment_ids"]:
        machine = read_equipment(api, equipment_id)
        assert_fields(machine, support_status="SUPPORTED", replacement_recommended=False)
        assert_null_fields(machine, "eos_notified_at")
        assert_common_fields(machine, expected_version=1)

    contract = read_contract(api, fleet["contract_id"])
    assert_fields(
        contract,
        obsolete_unit_count=0,
        replacement_candidate_count=0,
        fleet_renewal_risk="LOW",
    )


def test_end_of_support_on_a_critical_spare_notifies_every_unit_of_the_model(api, planner):
    """
    Announced stock keeps the ordinary threshold, so every unit is notified but none flips.

    PRD: "Hop one: every machine whose `model_id` matches the part's takes a new
    `support_status` — `END_OF_SUPPORT_ANNOUNCED` when the part became announced,
    `UNSUPPORTED` when the part became obsolete — and has `eos_notified_at` stamped from
    the clock."

    Design: Corner/state_machines/end_of_support_touches_the_fleet_only_for_a_critical_spare
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-EO-1", "SN-EO-2"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
    )
    controller = new_part(
        api,
        fleet["model_id"],
        part_number="MOTOR-CTRL",
        category="ELECTRONIC",
        unit_price_cents=90000,
        is_critical_spare=True,
        initial_refurb_qty=1,
    )

    declared = get_success_data(api.declare_end_of_support(controller["id"], planner), 200)
    # Refurbished stock survives, so the part stops one step short of obsolete.
    assert_fields(declared, lifecycle_status="END_OF_SUPPORT_ANNOUNCED", refurb_on_hand_qty=1)
    assert_instant(declared["eos_declared_at"], "2026-08-15T08:00:00Z", "eos_declared_at")
    assert_common_fields(declared, expected_version=2)

    for equipment_id in fleet["equipment_ids"]:
        machine = read_equipment(api, equipment_id)
        assert_fields(machine, support_status="END_OF_SUPPORT_ANNOUNCED")
        assert_instant(
            machine["eos_notified_at"], "2026-08-15T08:00:00Z", "eos_notified_at"
        )
        assert_common_fields(machine, expected_version=2)
        # An announced machine keeps the ordinary 40.00 threshold, and 93.50 is nowhere
        # near it, so the notification does not make it a replacement candidate.
        assert_two_decimals(machine["health_score"], 93.50)
        assert_fields(machine, replacement_recommended=False)

    contract = read_contract(api, fleet["contract_id"])
    # Only full UNSUPPORTED units count as obsolete, so every roll-up stays where it was.
    assert_fields(
        contract,
        obsolete_unit_count=0,
        replacement_candidate_count=0,
        fleet_renewal_risk="LOW",
    )


# ─── Certification first, then completion earns the credit ────────────────────


def test_certifying_before_completion_lets_completion_flip_the_credit_flag(api):
    """
    The documentation dimension certifies while the visit still runs, so completion pays.

    PRD: "Because the two dimensions advance independently, the flag can be set by either
    event arriving second — completion sets it when the documentation was already
    certified, and certification sets it when the visit was already completed."

    Design: Corner/state_machines/certifying_the_document_first_makes_completion_earn_the_credit_immediately
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T07:00:00Z",
        model_kwargs={
            "checklist_template": [
                checklist_item("BELT_TENSION", consumable=True),
                checklist_item("EMERGENCY_STOP", is_safety_critical=True),
            ]
        },
        serials=["SN-PM-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH, INSPECTOR_TECH_NORTH],
    )
    visiting_technician, inspector = fleet["technician_ids"]
    equipment_id = fleet["equipment_ids"][0]
    record_usage(api, equipment_id, 800)

    visit = schedule_visit(
        api,
        fleet["contract_id"],
        equipment_id,
        "2026-08-15T08:00:00Z",
        "2026-08-15T09:30:00Z",
        visiting_technician,
    )
    assert_fields(visit, safety_doc_status="PENDING", checklist_total_count=2)

    set_clock(api, "2026-08-15T08:00:00Z")
    start_visit(api, visit["id"], visiting_technician)
    for code, replaced in (("BELT_TENSION", True), ("EMERGENCY_STOP", None)):
        get_success_data(
            api.record_checklist_result(
                visit["id"],
                checklist_result_payload(code, result="PASS", consumable_replaced=replaced),
                technician_headers(visiting_technician),
            ),
            200,
        )
    counted = read_visit(api, visit["id"])
    assert_fields(
        counted,
        checklist_resolved_count=2,
        checklist_failed_count=0,
        safety_critical_failed_count=0,
        consumables_replaced_count=1,
    )

    get_success_data(
        api.submit_safety_doc(
            visit["id"],
            safety_doc_submit_payload(),
            technician_headers(visiting_technician),
        ),
        200,
    )
    certified = get_success_data(
        api.certify_safety_doc(visit["id"], inspector_headers(inspector)), 200
    )
    assert_fields(
        certified,
        safety_doc_status="CERTIFIED",
        safety_doc_certified_by_id=inspector,
        visit_status="IN_PROGRESS",
        pm_credit_earned=False,
    )

    set_clock(api, "2026-08-15T09:00:00Z")
    completed = get_success_data(
        api.complete_visit(visit["id"], technician_headers(visiting_technician)), 200
    )
    # The second of the two conditions arrives, so the same response already pays out.
    assert_fields(completed, visit_status="COMPLETED", pm_credit_earned=True)
    assert_instant(completed["completed_at"], "2026-08-15T09:00:00Z", "completed_at")


def test_completion_after_certification_resets_the_pm_baseline_and_compliance(api):
    """
    Completion captures the meter, clears the due status and credits the compliance count.

    PRD: "Completion sets `visit_status` to `COMPLETED`, stamps `completed_at`, captures
    the machine's current `usage_hours` into `usage_hours_at_visit` and writes the same
    figure back into the machine's `usage_hours_at_last_pm`, which recomputes `pm_status`
    to `OK`."

    Design: Corner/state_machines/certifying_the_document_first_makes_completion_earn_the_credit_immediately
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T07:00:00Z",
        model_kwargs={
            "checklist_template": [
                checklist_item("BELT_TENSION", consumable=True),
                checklist_item("EMERGENCY_STOP", is_safety_critical=True),
            ]
        },
        serials=["SN-PM-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH, INSPECTOR_TECH_NORTH],
    )
    visiting_technician, inspector = fleet["technician_ids"]
    equipment_id = fleet["equipment_ids"][0]
    record_usage(api, equipment_id, 800)
    # 800 - 500 is 300 hours against a 250-hour interval, short of 1.25 times it.
    assert_fields(read_equipment(api, equipment_id), pm_status="DUE")

    visit = schedule_visit(
        api,
        fleet["contract_id"],
        equipment_id,
        "2026-08-15T08:00:00Z",
        "2026-08-15T09:30:00Z",
        visiting_technician,
    )
    set_clock(api, "2026-08-15T08:00:00Z")
    start_visit(api, visit["id"], visiting_technician)
    for code in ("BELT_TENSION", "EMERGENCY_STOP"):
        get_success_data(
            api.record_checklist_result(
                visit["id"],
                checklist_result_payload(code, result="PASS"),
                technician_headers(visiting_technician),
            ),
            200,
        )
    get_success_data(
        api.submit_safety_doc(
            visit["id"],
            safety_doc_submit_payload(),
            technician_headers(visiting_technician),
        ),
        200,
    )
    get_success_data(
        api.certify_safety_doc(visit["id"], inspector_headers(inspector)), 200
    )

    set_clock(api, "2026-08-15T09:00:00Z")
    completed = get_success_data(
        api.complete_visit(visit["id"], technician_headers(visiting_technician)), 200
    )
    assert_fields(completed, visit_status="COMPLETED", pm_credit_earned=True)
    assert_two_decimals(completed["usage_hours_at_visit"], 800.00)
    # booked 1, started 2, two checklist results 3 and 4, submitted 5, certified 6,
    # completed 7.
    assert_common_fields(completed, expected_version=7)

    machine = read_equipment(api, equipment_id)
    assert_fields(machine, pm_status="OK")
    assert_two_decimals(machine["usage_hours_at_last_pm"], 800.00)

    assignment = assignment_for_visit(api, visit["id"])
    assert_fields(assignment, status="COMPLETED")
    freed = read_technician(api, visiting_technician)
    assert freed["committed_minutes"] == 0
    assert_technician_capacity_identity(freed, [assignment])

    contract = read_contract(api, fleet["contract_id"])
    assert_fields(contract, pm_visits_completed_count=1, pm_visits_missed_count=0)
    assert_two_decimals(contract["pm_compliance_pct"], 100.00)


# ─── The parts cycle is bounded at three, and each pass must be settled ───────


def test_resuming_with_an_allocation_still_outstanding_is_refused(api, planner):
    """
    A call cannot leave parts hold while one of its orders is still ALLOCATED.

    PRD: "Resuming returns `PARTS_HOLD` → `ON_SITE`, and is permitted only when no
    `PartOrder` on the call is still in status `ALLOCATED` — every ordered part must have
    been installed or cancelled first, or the answer is `ERR_UNRESOLVED_PART_ORDER`."

    Design: Corner/state_machines/parts_cycle_runs_three_times_and_refuses_a_fourth
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-PC-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    technician_id = fleet["technician_ids"][0]
    part = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=10,
    )
    call = open_call(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_WORN",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)
    arrived = arrive_call(api, call["id"], technician_id)
    assert_fields(arrived, status="ON_SITE", response_minutes=0, sla_met=True)

    place_hold(api, call["id"], technician_id, part["id"], qty=1, source="NEW")
    held = read_call(api, call["id"])
    assert_fields(held, status="PARTS_HOLD", parts_hold_count=1)

    refused = api.resume_service_call(call["id"], technician_headers(technician_id))
    validate_error(refused, ERR_UNRESOLVED_PART_ORDER, 409)

    unchanged = read_call(api, call["id"])
    assert_fields(unchanged, status="PARTS_HOLD", parts_hold_count=1)
    assert_common_fields(unchanged, expected_version=held["version"])
    outstanding = rows_of(
        api.list_part_orders(planner, service_call_id=call["id"], status="ALLOCATED")
    )
    assert len(outstanding) == 1, f"expected one outstanding order, got {len(outstanding)}"


def test_the_fourth_parts_hold_is_refused_and_the_response_clock_never_moves(api, planner):
    """
    Three settled hold-install-resume passes are legal and the fourth hold hits the limit.

    PRD: "A hold is permitted only while `parts_hold_count` is strictly below three, so a
    call may enter the cycle a first, second and third time; the fourth attempt is refused
    with `ERR_PARTS_HOLD_LIMIT`."

    Design: Corner/state_machines/parts_cycle_runs_three_times_and_refuses_a_fourth
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T08:00:00Z",
        serials=["SN-PC-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    contract_id = fleet["contract_id"]
    technician_id = fleet["technician_ids"][0]
    part = new_part(
        api,
        fleet["model_id"],
        part_number="BELT-STD",
        category="WEAR",
        unit_price_cents=8000,
        initial_on_hand_qty=10,
    )
    call = open_call(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        severity="MAJOR",
        symptom_code="BELT_WORN",
    )
    dispatch_call(api, call["id"], "2026-08-15T08:00:00Z", technician_id)
    arrive_call(api, call["id"], technician_id)

    for expected_count in (1, 2, 3):
        place_hold(api, call["id"], technician_id, part["id"], qty=1, source="NEW")
        on_hold = read_call(api, call["id"])
        assert_fields(on_hold, status="PARTS_HOLD", parts_hold_count=expected_count)
        allocated = rows_of(
            api.list_part_orders(planner, service_call_id=call["id"], status="ALLOCATED")
        )
        assert len(allocated) == 1, f"expected one open order, got {len(allocated)}"
        get_success_data(
            api.install_part_order(allocated[0]["id"], technician_headers(technician_id)),
            200,
        )
        resumed = get_success_data(
            api.resume_service_call(call["id"], technician_headers(technician_id)), 200
        )
        assert_fields(resumed, status="ON_SITE", parts_hold_count=expected_count)

    refused = api.place_parts_hold(
        call["id"],
        parts_hold_payload(part["id"], 1, "NEW"),
        technician_headers(technician_id),
    )
    validate_error(refused, ERR_PARTS_HOLD_LIMIT, 409)

    after = read_call(api, call["id"])
    assert_fields(after, status="ON_SITE", parts_hold_count=3)
    # "Resuming deliberately does not touch arrived_at, response_minutes or sla_met."
    assert_instant(after["arrived_at"], "2026-08-15T08:00:00Z", "arrived_at")
    assert_fields(after, response_minutes=0, sla_met=True)

    orders = rows_of(api.list_part_orders(planner, service_call_id=call["id"]))
    assert len(orders) == 3, f"expected exactly three part orders, got {len(orders)}"
    assert all(o["status"] == "INSTALLED" for o in orders), "every pass must be settled"

    after_part = read_part(api, part["id"])
    assert_fields(after_part, on_hand_qty=7, allocated_qty=0)
    assert_part_inventory_identity(after_part, orders)

    contract = read_contract(api, contract_id)
    # 500,000 opening allowance less three fully covered 8,000-cent draws.
    assert_money(contract["parts_allowance_remaining_cents"], 476000, "allowance remaining")
    assert_parts_allowance_identity(contract, orders)


# ─── Marking a visit missed waits for the window to close ─────────────────────


def test_marking_a_visit_missed_before_the_window_closes_is_refused(api, coordinator):
    """
    Inside the window, and one second short of its end, the visit is untouched.

    PRD: "**Marking missed** requires the same `SCHEDULED` starting point *and* a logical
    clock at or after `window_end`; an attempt before the window has closed answers
    `ERR_VISIT_INVALID_STATE`."

    Design: Corner/state_machines/mark_missed_needs_the_window_to_have_closed_first
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T07:00:00Z",
        serials=["SN-MM-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    technician_id = fleet["technician_ids"][0]
    visit = schedule_visit(
        api,
        fleet["contract_id"],
        fleet["equipment_ids"][0],
        "2026-08-15T08:00:00Z",
        "2026-08-15T09:30:00Z",
        technician_id,
    )
    assert_fields(visit, visit_status="SCHEDULED", planned_minutes=90)

    set_clock(api, "2026-08-15T09:00:00Z")
    validate_error(
        api.mark_visit_missed(visit["id"], coordinator), ERR_VISIT_INVALID_STATE, 409
    )

    set_clock(api, "2026-08-15T09:29:59Z")
    validate_error(
        api.mark_visit_missed(visit["id"], coordinator), ERR_VISIT_INVALID_STATE, 409
    )

    unchanged = read_visit(api, visit["id"])
    assert_fields(unchanged, visit_status="SCHEDULED")
    assert_common_fields(unchanged, expected_version=1)
    assignment = assignment_for_visit(api, visit["id"])
    assert_fields(assignment, status="RESERVED", planned_minutes=90)
    assert_null_fields(assignment, "release_reason")
    still_committed = read_technician(api, technician_id)
    assert still_committed["committed_minutes"] == 90
    assert_technician_capacity_identity(still_committed, [assignment])


def test_marking_a_visit_missed_exactly_at_window_end_damages_compliance(api, coordinator):
    """
    At the closing instant the visit is missed, the slot is released and compliance drops.

    PRD: "It moves `visit_status` to `MISSED`, releases the assignment with
    `release_reason` `VISIT_MISSED`, returns the minutes, raises `pm_visits_missed_count`
    by one and recomputes `pm_compliance_pct`."

    Design: Corner/state_machines/mark_missed_needs_the_window_to_have_closed_first
    """
    fleet = build_fleet(
        api,
        clock="2026-08-15T07:00:00Z",
        serials=["SN-MM-1"],
        equipment_kwargs={"initial_usage_hours": 500},
        contract_kwargs={"annual_base_cents": 140000},
        technicians=[TREADMILL_TECH_NORTH],
    )
    contract_id = fleet["contract_id"]
    technician_id = fleet["technician_ids"][0]
    visit = schedule_visit(
        api,
        contract_id,
        fleet["equipment_ids"][0],
        "2026-08-15T08:00:00Z",
        "2026-08-15T09:30:00Z",
        technician_id,
    )

    set_clock(api, "2026-08-15T09:30:00Z")
    missed = get_success_data(api.mark_visit_missed(visit["id"], coordinator), 200)
    assert_fields(missed, visit_status="MISSED")
    assert_common_fields(missed, expected_version=2)

    assignment = assignment_for_visit(api, visit["id"])
    assert_fields(assignment, status="RELEASED", release_reason="VISIT_MISSED")
    assert_common_fields(assignment, expected_version=2)
    freed = read_technician(api, technician_id)
    assert freed["committed_minutes"] == 0
    assert_technician_capacity_identity(freed, [assignment])

    contract = read_contract(api, contract_id)
    assert_fields(contract, pm_visits_completed_count=0, pm_visits_missed_count=1)
    # One hundred times zero completed over a denominator of one.
    assert_two_decimals(contract["pm_compliance_pct"], 0.00)
