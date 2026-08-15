"""Non-linear state-machine cycles and transitive cascades across entities."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    get_artist, get_reservation, get_unit, get_stop, get_line, get_tour,
    find_ticket_for_unit, settle_reservation,
    setup_substitution_cycle, setup_maintenance_ticket_via_gate,
    setup_loadout_cascade, setup_vendor_suspend_pair, setup_stage_guard,
    setup_cross_rental_fulfilled,
    api_client, TEST_USERS, make_vendor_rep_headers, create_shipment_payload,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]
LC = TEST_USERS["logistics_headers"]
WT = TEST_USERS["warehouse_tech_headers"]


def test_substitution_revision_cycle_reaches_approved(api, tour_manager_headers):
    """PRD §3.4: "Rejection, also a `TourManager` call, loops the line from
    `SUBSTITUTION_PENDING` back to `SOURCED` and advances the stop's
    `rider_revision`; the cycle from `SOURCED` through `SUBSTITUTION_PENDING`
    and back to `SOURCED` is permitted and may repeat."
    PRD §3.2: "its creation — like every later mutation of any rider line on
    that stop — advances the parent stop's `rider_revision`".

    Design: Difficulty/non_linear_state_machine/rider_line_substitution_revision_cycle
    """
    ctx = setup_substitution_cycle()
    rev0 = ctx["rev0"]
    # Every mutation advanced the stop's rider revision by exactly one.
    assert ctx["rev_after_propose1"] == rev0 + 1
    assert ctx["rev_after_reject"] == rev0 + 2
    assert ctx["rev_after_propose2"] == rev0 + 3

    approved = validate_success(api.approve_substitution(
        ctx["line"]["id"],
        {"expected_tour_stop_rider_revision": ctx["rev_after_propose2"]},
        tour_manager_headers))
    assert approved["status"] == "APPROVED"


def test_substitution_approval_swap_effects(api, tour_manager_headers):
    """PRD §3.4: "Approval is a swap executed as a paired cancel-and-create. The
    old reservation transitions from `SOURCED` to `CANCELLED`; its unit is
    released from `RESERVED` back to `AVAILABLE`; and its held deposit is
    credited back to the artist. A new reservation is created against a unit of
    the substitute model, that unit moves from `AVAILABLE` to `RESERVED`, and a
    fresh quote and hold are computed and debited".

    Design: Difficulty/non_linear_state_machine/rider_line_substitution_revision_cycle
    """
    ctx = setup_substitution_cycle()
    approved = validate_success(api.approve_substitution(
        ctx["line"]["id"],
        {"expected_tour_stop_rider_revision": ctx["rev_after_propose2"]},
        tour_manager_headers))
    assert approved["status"] == "APPROVED"

    old = get_reservation(ctx["reservation"]["id"])
    assert old["status"] == "CANCELLED"
    old_unit = get_unit(ctx["u1"]["id"])
    assert old_unit["status"] == "AVAILABLE"
    assert old_unit["active_reservation_id"] is None

    new_unit = get_unit(ctx["u2"]["id"])
    assert new_unit["status"] == "RESERVED"
    assert new_unit["active_reservation_id"] is not None
    assert new_unit["active_reservation_id"] != ctx["reservation"]["id"]


def test_maintenance_parts_cycle_completes(api, warehouse_tech_headers):
    """PRD §3.6: "From there a `WarehouseTech` starts work — `OPEN` to
    `IN_PROGRESS` — parks it waiting for parts — `IN_PROGRESS` to
    `AWAITING_PARTS` — and resumes it, with the loop between `IN_PROGRESS` and
    `AWAITING_PARTS` permitted to repeat."

    Design: Difficulty/non_linear_state_machine/maintenance_ticket_parts_awaiting_cycle
    """
    ctx = setup_maintenance_ticket_via_gate()
    ticket = ctx["ticket"]
    assert ticket["status"] == "OPEN"
    assert ticket["opened_reason"] == "SCHEDULED_CYCLE"

    validate_success(api.start_maintenance_ticket(ticket["id"], warehouse_tech_headers))
    for _ in range(2):
        parked = validate_success(api.await_parts_maintenance_ticket(ticket["id"],
                                                                     warehouse_tech_headers))
        assert parked["status"] == "AWAITING_PARTS"
        resumed = validate_success(api.resume_maintenance_ticket(ticket["id"],
                                                                 warehouse_tech_headers))
        assert resumed["status"] == "IN_PROGRESS"

    completed = validate_success(api.complete_maintenance_ticket(
        ticket["id"], {"service_cost_cents": 15_000, "condition_delta": 20},
        warehouse_tech_headers))
    assert completed["status"] == "COMPLETED"


def test_maintenance_completion_restores_unit(api, warehouse_tech_headers):
    """PRD §3.6: "Completion — `IN_PROGRESS` to `COMPLETED` — requires the
    technician to supply the actual `service_cost_cents` (non-negative) and a
    `condition_delta` between 0 and 100: the unit's `condition_score` climbs by
    the delta, capped so it never exceeds 100, its `rental_days_since_service`
    resets to zero, its `active_reservation_id` clears, the unit returns from
    `MAINTENANCE` to `AVAILABLE`, and the ticket's `closed_at` is stamped."

    Design: Difficulty/non_linear_state_machine/maintenance_ticket_parts_awaiting_cycle
    """
    ctx = setup_maintenance_ticket_via_gate()
    ticket = ctx["ticket"]
    unit_id = ctx["unit"]["id"]
    assert get_unit(unit_id)["status"] == "MAINTENANCE"

    validate_success(api.start_maintenance_ticket(ticket["id"], warehouse_tech_headers))
    validate_success(api.await_parts_maintenance_ticket(ticket["id"], warehouse_tech_headers))
    validate_success(api.resume_maintenance_ticket(ticket["id"], warehouse_tech_headers))
    completed = validate_success(api.complete_maintenance_ticket(
        ticket["id"], {"service_cost_cents": 15_000, "condition_delta": 20},
        warehouse_tech_headers))
    assert completed["closed_at"] is not None

    unit = get_unit(unit_id)
    assert unit["status"] == "AVAILABLE"
    assert unit["rental_days_since_service"] == 0
    # min(100, 100 + 20): the condition score is capped at 100.
    assert unit["condition_score"] == 100


def test_stop_loadout_cascade_states(api, warehouse_tech_headers):
    """PRD §3.6: "Load-out, also a `WarehouseTech` action, moves the stop from
    `SHOW_READY` to `LOADED_OUT` and sweeps every `DELIVERED` reservation
    feeding the stop into `RETURNED`, running the check-in cascade on each
    affected unit."
    PRD §3.6: "A clean return moves the unit from `OUT_ON_RENTAL` to
    `AVAILABLE`, adds the reservation's rental days to its
    `rental_days_since_service`, and clears its `active_reservation_id`."
    — the first 25-day rental returns clean and accumulates 25 days; the second
    5-day rental projects to 30 at load-out.

    Design: Difficulty/transitive_cascade/stop_loadout_cascade_depth3
    """
    ctx = setup_loadout_cascade()
    assert ctx["days_after_first"] == 25

    loaded_out = validate_success(api.load_out_tour_stop(ctx["stop"]["id"],
                                                         warehouse_tech_headers))
    assert loaded_out["status"] == "LOADED_OUT"
    assert get_reservation(ctx["reservation"]["id"])["status"] == "RETURNED"
    assert get_unit(ctx["unit"]["id"])["status"] == "MAINTENANCE"


def test_stop_loadout_cascade_opens_ticket(api, warehouse_tech_headers):
    """PRD §3.6: "the gate projects the unit's `rental_days_since_service` plus
    the days of the returning reservation, and when that projection reaches 30 —
    exactly 30 included — or the unit's `condition_score` has fallen below 40,
    the unit moves from `OUT_ON_RENTAL` (or `IN_TRANSIT`, if a claim or a leg
    left it there) to `MAINTENANCE` instead of back to the pool, and a
    maintenance ticket is opened with `opened_reason` `SCHEDULED_CYCLE` when the
    day threshold tripped or `CONDITION_THRESHOLD` when the condition did."
    Projected 25 + 5 = 30 trips the gate; the ticket opened is the fourth
    observable mutation of the depth-3 chain.

    Design: Difficulty/transitive_cascade/stop_loadout_cascade_depth3
    """
    ctx = setup_loadout_cascade()
    validate_success(api.load_out_tour_stop(ctx["stop"]["id"], warehouse_tech_headers))

    ticket = find_ticket_for_unit(ctx["unit"]["id"])
    assert ticket["status"] == "OPEN"
    assert ticket["opened_reason"] == "SCHEDULED_CYCLE"
    assert ticket["gear_unit_id"] == ctx["unit"]["id"]


def test_vendor_suspend_cancels_open_requests(api, ops_manager_headers):
    """PRD §3.8: "suspension moves an `APPROVED` vendor to `SUSPENDED` and
    cancels every cross-rental request of that vendor still sitting in
    `REQUESTED` or `ACCEPTED`".

    Design: Difficulty/transitive_cascade/vendor_suspend_cascade_depth2
    """
    ctx = setup_vendor_suspend_pair()
    suspended = validate_success(api.suspend_partner_vendor(ctx["vendor"]["id"],
                                                            ops_manager_headers))
    assert suspended["status"] == "SUSPENDED"
    crr1 = validate_success(api.get_cross_rental_request(ctx["crr1"]["id"], LC))
    crr2 = validate_success(api.get_cross_rental_request(ctx["crr2"]["id"], LC))
    assert crr1["status"] == "CANCELLED"   # was ACCEPTED
    assert crr2["status"] == "CANCELLED"   # was REQUESTED


def test_vendor_reinstatement_cycle_after_suspend(api, ops_manager_headers):
    """PRD §3.8: "reinstatement from `SUSPENDED` back to `APPROVED` is permitted
    and the cycle may repeat."

    Design: Difficulty/transitive_cascade/vendor_suspend_cascade_depth2
    """
    ctx = setup_vendor_suspend_pair()
    validate_success(api.suspend_partner_vendor(ctx["vendor"]["id"], ops_manager_headers))
    reinstated = validate_success(api.approve_partner_vendor(ctx["vendor"]["id"],
                                                             ops_manager_headers))
    assert reinstated["status"] == "APPROVED"
    # The cancelled requests were terminal and stay cancelled.
    assert validate_success(api.get_cross_rental_request(ctx["crr1"]["id"], LC))["status"] == "CANCELLED"


def test_stage_blocked_on_draft_tour(api, logistics_headers):
    """PRD §3.6: "Staging — `PLANNED` to `GEAR_STAGED`, a `LogisticsCoordinator`
    action — demands an `ACTIVE` parent tour, every rider line of the stop
    resolved to `SOURCED`, `APPROVED`, `FULFILLED`, or `CANCELLED` with nothing
    left in `REQUESTED` or `SUBSTITUTION_PENDING`, and at least one delivered
    cartage leg bound for the stop's `city_code`."
    PRD §2.11: "4. State legality — a target whose current state does not permit
    the requested transition fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/stop_stage_depends_on_tour_active
    """
    ctx = setup_stage_guard()
    assert get_tour(ctx["tour"]["id"])["status"] == "DRAFT"
    resp = api.stage_tour_stop(ctx["stop"]["id"], logistics_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_stage_succeeds_once_tour_active(api, logistics_headers, tour_manager_headers):
    """PRD §3.6: "Staging — `PLANNED` to `GEAR_STAGED`, a `LogisticsCoordinator`
    action — demands an `ACTIVE` parent tour, every rider line of the stop
    resolved to `SOURCED`, `APPROVED`, `FULFILLED`, or `CANCELLED` with nothing
    left in `REQUESTED` or `SUBSTITUTION_PENDING`, and at least one delivered
    cartage leg bound for the stop's `city_code`."

    Design: Difficulty/cross_entity_state_dependency/stop_stage_depends_on_tour_active
    """
    from test_helpers import activate_tour
    ctx = setup_stage_guard()
    activate_tour(ctx["tour"]["id"], tour_manager_headers)
    staged = validate_success(api.stage_tour_stop(ctx["stop"]["id"], logistics_headers))
    assert staged["status"] == "GEAR_STAGED"


def test_crossrental_settle_blocked_until_reservation_settled(api, ops_manager_headers):
    """PRD §3.8: "Once the linked reservation itself has settled, an
    `OpsManager` settles the cross-rental — `FULFILLED` to `SETTLED`".
    PRD §2.11: "4. State legality — a target whose current state does not permit
    the requested transition fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/crossrental_settle_depends_on_reservation_settled
    """
    ctx = setup_cross_rental_fulfilled()
    # Linked reservation is merely SOURCED — the cross-entity gate blocks.
    assert get_reservation(ctx["reservation"]["id"])["status"] == "SOURCED"
    resp = api.settle_cross_rental_request(ctx["crr"]["id"], ops_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_crossrental_settle_computes_commission(api, ops_manager_headers):
    """PRD §3.8: "Once the linked reservation itself has settled, an
    `OpsManager` settles the cross-rental — `FULFILLED` to `SETTLED` — which
    computes the `commission_cents` owed by the vendor: the vendor's revenue for
    the window — the `vendor_rate_cents_per_day` times the reservation's day
    count — multiplied by the vendor's `commission_bps` and divided by ten
    thousand, rounded half-up to whole cents".
    80000 cents/day * 2 days * 1500 / 10000 = 24000.

    Design: Difficulty/cross_entity_state_dependency/crossrental_settle_depends_on_reservation_settled
    """
    from test_helpers import activate_tour
    ctx = setup_cross_rental_fulfilled()
    tour = activate_tour(ctx["tour"]["id"], TM)
    # A leg bound for the destination city satisfies the dispatch precondition.
    validate_success(api.create_shipment(
        create_shipment_payload(tour["id"], from_city_code="SEA", to_city_code="SEA",
                                ship_date="2026-08-10T00:00:00Z", capacity_kg=1000), LC), 201)
    validate_success(api.dispatch_reservation(ctx["reservation"]["id"], LC))
    validate_success(api.mark_reservation_delivered(ctx["reservation"]["id"], LC))
    validate_success(api.check_in_reservation(ctx["reservation"]["id"],
                                              {"checked_in_at": "2026-08-12T09:00:00Z"}, WT))
    validate_success(api.inspect_reservation(ctx["reservation"]["id"],
                                             {"damage_present": False}, WT))
    settled_res = settle_reservation(ctx["reservation"]["id"], TM)
    assert settled_res["status"] == "SETTLED"

    settled_req = validate_success(api.settle_cross_rental_request(ctx["crr"]["id"],
                                                                   ops_manager_headers))
    assert settled_req["status"] == "SETTLED"
    assert settled_req["commission_cents"] == 24_000
