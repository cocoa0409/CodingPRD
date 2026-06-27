"""State-machine shape (parallel axes, cyclic dispute loop) and transitive
cascades (deadout depth-3, treatment depth-2), plus corner state-machine and
consistency-model instances.

Covers difficulty queue-A rules non_linear_state_machine and transitive_cascade,
and the corner-queue state_machines / consistency_model / cross-cutting
(derived reconciliation) instances. Each test's Design tag names its source.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    create_inspection_payload, create_harvest_payload,
    TEST_USERS, make_apiary_manager_headers,
    create_apiary, create_registered_apiary, create_pending_registration,
    create_hive, create_inspected_hive,
    setup_lot_with_harvests, setup_blocked_lot,
    create_signed_contract, propose_placement, confirm_placement_fresh,
    setup_placed_contract, current_contract_version, set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
APIARIST = TEST_USERS["state_apiarist_headers"]
COORDINATOR = TEST_USERS["contract_coordinator_headers"]


# ─── non_linear_state_machine / hive_parallel_axes ──────────────────────────
def test_mark_queenless_leaves_health_unchanged(api):
    """PRD §2.6: "A change on one axis does not, by itself, move the other — for
    example marking a colony `QUEENLESS` leaves `health_status` untouched."

    Design: Difficulty/non_linear_state_machine/hive_parallel_axes_health_and_queen_evolve_independently
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)

    updated = validate_success(api.mark_queenless(hive["id"], headers), 200)
    assert updated["queen_status"] == "QUEENLESS"
    assert updated["health_status"] == "HEALTHY"


def test_quarantine_leaves_queen_axis_unchanged(api):
    """PRD §2.6: "A change on one axis does not, by itself, move the other — for
    example marking a colony `QUEENLESS` leaves `health_status` untouched."
    PRD §3.2: "Quarantining a colony moves `health_status` from `HEALTHY` to
    `QUARANTINE` and, as a side effect, cancels any `PROPOSED` hive placement of
    that colony."

    Design: Difficulty/non_linear_state_machine/hive_parallel_axes_health_and_queen_evolve_independently
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)

    updated = validate_success(api.quarantine_hive(hive["id"], headers), 200)
    assert updated["health_status"] == "QUARANTINE"
    assert updated["queen_status"] == "QUEENRIGHT"


# ─── non_linear_state_machine / contract_cyclic_disputed_back_to_placed ─────
def test_contract_dispute_then_resolve_returns_to_placed(api):
    """PRD §3.6: "A `PLACED` contract may be disputed, moving it from `PLACED` to
    `DISPUTED` and freezing the payout pending re-placement. Resolving the dispute
    moves it back from `DISPUTED` to `PLACED` (the cyclic loop), permitted only when
    `placed_strong_hives` is again at or above `required_strong_hives`, and
    recomputes the payout."

    Design: Difficulty/non_linear_state_machine/contract_cyclic_disputed_back_to_placed
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract, _ = setup_placed_contract(apiary["id"], [hive["id"]],
                                        required_strong_hives=1)
    assert contract["status"] == "PLACED"

    disputed = validate_success(api.dispute_contract(contract["id"], COORDINATOR), 200)
    assert disputed["status"] == "DISPUTED"

    resolved = validate_success(api.resolve_dispute(contract["id"], COORDINATOR), 200)
    assert resolved["status"] == "PLACED"


def test_contract_resolve_dispute_revisits_placed_state(api):
    """PRD §3.6: "Resolving the dispute moves it back from `DISPUTED` to `PLACED`
    (the cyclic loop), permitted only when `placed_strong_hives` is again at or
    above `required_strong_hives`, and recomputes the payout."

    Design: Difficulty/non_linear_state_machine/contract_cyclic_disputed_back_to_placed
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract, _ = setup_placed_contract(apiary["id"], [hive["id"]],
                                        required_strong_hives=1)
    validate_success(api.dispute_contract(contract["id"], COORDINATOR), 200)
    resolved = validate_success(api.resolve_dispute(contract["id"], COORDINATOR), 200)
    assert resolved["status"] == "PLACED"
    assert resolved["placed_strong_hives"] == 1


# ─── transitive_cascade / deadout depth-3 ───────────────────────────────────
def test_deadout_cascades_to_placement_and_contract_understaffed(api):
    """PRD §3.2: "for every `CONFIRMED` hive placement of the dead colony, that
    placement transitions from `CONFIRMED` to `REMOVED`, and if its `grade` was
    `CONTRACT_GRADE` the parent contract's `placed_strong_hives` is decremented."
    PRD §3.2: "for each contract so affected, if it is currently in `PLACED` and its
    `placed_strong_hives` has fallen below its `required_strong_hives`, the contract
    transitions from `PLACED` to `UNDERSTAFFED` and its `projected_payout_cents` is
    recomputed from the remaining confirmed placements."

    Design: Difficulty/transitive_cascade/deadout_cascade_hive_to_placement_to_contract_understaffed
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    h1 = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                               brood_frames_observed=5)
    h2 = create_inspected_hive(apiary["id"], tag="H2", brood_frames=5,
                               brood_frames_observed=5)
    contract, placements = setup_placed_contract(
        apiary["id"], [h1["id"], h2["id"]], required_strong_hives=2)
    assert contract["projected_payout_cents"] == 58000
    p1 = placements[0]

    headers = make_apiary_manager_headers(apiary["id"])
    dead = validate_success(api.deadout_hive(h1["id"], headers), 200)
    assert dead["health_status"] == "DEADOUT"

    p1_after = validate_success(api.get_placement(p1["id"], COORDINATOR), 200)
    assert p1_after["status"] == "REMOVED"

    contract_after = validate_success(api.get_contract(contract["id"], COORDINATOR), 200)
    assert contract_after["placed_strong_hives"] == 1
    assert contract_after["status"] == "UNDERSTAFFED"
    # remaining 1 strong hive @100 -> 24000; shortfall 1 -> -5000; no bonus -> 19000
    assert contract_after["projected_payout_cents"] == 19000


def test_deadout_recomputes_apiary_colony_count(api):
    """PRD §3.2: "First, the owning apiary's `active_colony_count` is recomputed as
    the count of its non-`DEADOUT` hives, decrementing it."

    Design: Difficulty/transitive_cascade/deadout_cascade_hive_to_placement_to_contract_understaffed
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    h1 = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                               brood_frames_observed=5)
    h2 = create_inspected_hive(apiary["id"], tag="H2", brood_frames=5,
                               brood_frames_observed=5)
    setup_placed_contract(apiary["id"], [h1["id"], h2["id"]], required_strong_hives=2)
    headers = make_apiary_manager_headers(apiary["id"])

    validate_success(api.deadout_hive(h1["id"], headers), 200)
    ap_after = validate_success(api.get_apiary(apiary["id"], headers), 200)
    assert ap_after["active_colony_count"] == 1


# ─── transitive_cascade / treatment depth-2 ─────────────────────────────────
def test_treatment_blocks_hive_and_cascades_draft_lot_to_blocked(api):
    """PRD §3.4: "The colony's `harvest_blocked_until` field is then set to the
    latest (maximum) `harvest_clear_at` across all of the colony's `ACTIVE`
    treatments — the instant, exclusive, before which honey may not be pulled from
    this colony."
    PRD §3.4: "Applying a treatment also cascades into honey lots: if any `DRAFT`
    honey lot already holds a `RECORDED` harvest drawn from this colony, that lot
    transitions from `DRAFT` to `BLOCKED`, freezing it for extraction until the
    colony clears."

    Design: Difficulty/transitive_cascade/treatment_cascade_hive_block_to_lot_blocked
    """
    set_clock("2026-02-09T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, _ = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0)])

    tx = validate_success(api.create_treatment(
        hive["id"],
        create_treatment_payload_helper(product="APIVAR",
                                        applied_at="2026-02-10T00:00:00Z",
                                        duration_days=42), headers), 201)
    hive_after = validate_success(api.get_hive(hive["id"], headers), 200)
    assert hive_after["health_status"] == "TREATMENT"
    # applied 2026-02-10 + 42 duration + 14 withdrawal = 2026-04-07
    assert hive_after["harvest_blocked_until"] is not None
    assert hive_after["harvest_blocked_until"].startswith("2026-04-07")

    lot_after = validate_success(api.get_honey_lot(lot["id"], headers), 200)
    assert lot_after["status"] == "BLOCKED"


def test_treatment_sets_health_to_treatment(api):
    """PRD §3.4: "A treatment may be applied while the colony's `health_status` is
    `HEALTHY` or `QUARANTINE`, and applying it sets `health_status` to `TREATMENT`."

    Design: Difficulty/transitive_cascade/treatment_cascade_hive_block_to_lot_blocked
    """
    set_clock("2026-02-09T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)

    validate_success(api.create_treatment(
        hive["id"],
        create_treatment_payload_helper(product="APIVAR",
                                        applied_at="2026-02-10T00:00:00Z",
                                        duration_days=42), headers), 201)
    hive_after = validate_success(api.get_hive(hive["id"], headers), 200)
    assert hive_after["health_status"] == "TREATMENT"


# ─── Corner / state_machines ────────────────────────────────────────────────
def test_registration_approve_sets_apiary_status_active(api):
    """PRD §3.1: "Approving a registration moves it from `PENDING` to `ACTIVE`;
    this is permitted only when the registration is still `PENDING`, when the
    logical clock is at or after the `effective_date`, and when the clock is
    strictly before the `expiry_date`. Approval sets the owning apiary's
    `registration_status` to `ACTIVE` and increments the registration's `version`."

    Design: Corner/state_machines/registration_approve_pending_to_active_sets_apiary_status
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    reg = create_pending_registration(
        apiary["id"], registration_number="CA-001",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z")

    approved = validate_success(
        api.approve_registration(apiary["id"], reg["id"], APIARIST), 200)
    assert approved["status"] == "ACTIVE"
    ap = validate_success(api.get_apiary(apiary["id"], APIARIST), 200)
    assert ap["registration_status"] == "ACTIVE"


def test_sign_already_signed_contract_invalid_state(api):
    """PRD §3.5: "Signing a contract moves it from `DRAFT` to `SIGNED`; this
    requires the contract to be `DRAFT` and the `bloom_end` to be strictly after
    the `bloom_start`."

    Design: Corner/state_machines/sign_contract_from_signed_returns_invalid_state
    """
    contract = create_signed_contract(required_strong_hives=1)
    res = api.sign_contract(contract["id"], COORDINATOR)
    validate_error(res, "ERR_INVALID_STATE")


def test_requeen_start_before_due_date_too_early(api):
    """PRD §3.9: "Starting a scheduled requeen moves the schedule from `SCHEDULED`
    to the terminal `COMPLETED`, but only when the schedule is `SCHEDULED`, the
    logical clock has reached or passed the `due_date` (otherwise `ERR_TOO_EARLY`),
    and the colony is currently `QUEENLESS`."

    Design: Corner/state_machines/requeen_start_before_due_date_returns_too_early
    """
    set_clock("2026-03-01T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)
    validate_success(api.mark_queenless(hive["id"], headers), 200)
    sched = validate_success(api.create_requeen_schedule(
        hive["id"], {"due_date": "2026-04-01T00:00:00Z", "reason": "QUEENLESS"},
        headers), 201)

    res = api.start_requeen(sched["id"], headers)
    validate_error(res, "ERR_TOO_EARLY")


def test_deadout_terminal_second_deadout_rejected(api):
    """PRD §2.6: "The single exception is that `DEADOUT` on the health axis is
    terminal for the whole colony: once a hive is `DEADOUT` no further transition on
    either axis is permitted, and the queen axis is frozen wherever it stood."

    Design: Corner/state_machines/deadout_is_terminal_no_further_transition
    """
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)
    validate_success(api.deadout_hive(hive["id"], headers), 200)

    res = api.deadout_hive(hive["id"], headers)
    validate_error(res, "ERR_TERMINAL_STATE")


def test_clock_advance_expires_active_registration(api):
    """PRD §2.5: "whenever the logical clock is advanced, any `StateRegistration`
    currently in `ACTIVE` whose `expiry_date` is at or before the new clock value
    transitions from `ACTIVE` to `EXPIRED`, and the owning apiary's
    `registration_status` is set to `EXPIRED` in the same step."

    Design: Corner/state_machines/clock_advance_expires_active_registration
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary(expiry="2026-06-01T00:00:00Z")
    set_clock("2026-06-02T00:00:00Z")

    ap = validate_success(api.get_apiary(apiary["id"], APIARIST), 200)
    assert ap["registration_status"] == "EXPIRED"


def test_second_void_of_harvest_rejected_terminal(api):
    """PRD §3.7: "Voiding a single harvest moves it from `RECORDED` to the terminal
    `VOID`, but only while its parent lot is `DRAFT` or `BLOCKED`; doing so subtracts
    the contribution's `weight_kg` from the lot's `gross_weight_kg` and recomputes
    the provisional yield, preserving honey-mass conservation."

    Design: Corner/state_machines/harvest_void_idempotency_second_void_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot, rows = setup_lot_with_harvests(apiary["id"], hive["id"], [(4, 12.0)])
    hv = rows[0]
    validate_success(api.void_harvest(hv["id"], headers), 200)

    res = api.void_harvest(hv["id"], headers)
    validate_error(res, "ERR_TERMINAL_STATE")


def test_treatment_complete_clears_health_to_healthy(api):
    """PRD §3.4: "Completion recomputes the colony's `harvest_blocked_until` from
    the remaining `ACTIVE` treatments, and if no `ACTIVE` treatments remain the
    colony's `health_status` returns to `HEALTHY`."

    Design: Corner/state_machines/treatment_complete_clears_health_to_healthy
    """
    set_clock("2026-05-01T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    tx = validate_success(api.create_treatment(
        hive["id"],
        create_treatment_payload_helper(product="OXALIC_ACID",
                                        applied_at="2026-05-01T00:00:00Z",
                                        duration_days=1), headers), 201)
    set_clock("2026-05-03T00:00:00Z")

    completed = validate_success(api.complete_treatment(tx["id"], headers), 200)
    assert completed["status"] == "COMPLETED"
    hive_after = validate_success(api.get_hive(hive["id"], headers), 200)
    assert hive_after["health_status"] == "HEALTHY"


def test_cancel_confirmed_placement_rejected(api):
    """PRD §3.5: "A proposed placement can instead be cancelled, moving it from
    `PROPOSED` to `CANCELLED` with no further effect."

    Design: Corner/state_machines/placement_cancel_from_confirmed_rejected
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary, _ = create_registered_apiary()
    hive = create_inspected_hive(apiary["id"], tag="H1", brood_frames=5,
                                 brood_frames_observed=5)
    contract = create_signed_contract(required_strong_hives=1)
    placement = propose_placement(contract["id"], hive["id"])
    confirm_placement_fresh(contract["id"], placement["id"])

    res = api.cancel_placement(placement["id"], COORDINATOR)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner / consistency_model + cross_cutting derived reconciliation ──────
def test_harvest_credit_visible_immediately(api):
    """PRD §3.7: "Recording a harvest credits the lot's `gross_weight_kg` by the
    contribution's `weight_kg` and recomputes the lot's provisional yield."
    PRD §2.6: "Computed roll-ups ... are recomputed as part of the same operation
    that triggers them, so the system is always immediately consistent."

    Design: Corner/consistency_model/harvest_debit_visible_immediately_same_request
    """
    set_clock("2026-05-10T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=6)
    lot = validate_success(api.create_honey_lot(
        {"apiary_id": apiary["id"], "lot_code": "L1", "floral_source": "WILDFLOWER"},
        headers), 201)

    validate_success(api.create_harvest(
        lot["id"], create_harvest_payload(hive["id"], frames_pulled=5, weight_kg=15.0),
        headers), 201)
    lot_after = validate_success(api.get_honey_lot(lot["id"], headers), 200)
    assert lot_after["gross_weight_kg"] == 15.0


def test_inspections_reverse_reachable_by_hive(api):
    """PRD §3.3: "Each inspection references its colony through `hive_id`, and a
    hive's inspections can be listed."

    Design: Corner/cross_cutting_complexity_layers/fk_reverse_reachability_inspections_by_hive
    """
    set_clock("2026-01-06T00:00:00Z")
    apiary = create_apiary()
    headers = make_apiary_manager_headers(apiary["id"])
    hive = create_hive(apiary["id"], tag="H1", brood_frames=5)
    validate_success(api.create_inspection(
        hive["id"], create_inspection_payload(), headers), 201)

    data, meta = validate_paginated(api.list_inspections(hive["id"], headers))
    assert meta["total_count"] == 1
    assert data[0]["hive_id"] == hive["id"]


# Local helper: keep treatment payloads inline-customizable without re-importing
def create_treatment_payload_helper(product, applied_at, duration_days):
    return {"product": product, "applied_at": applied_at, "duration_days": duration_days}
