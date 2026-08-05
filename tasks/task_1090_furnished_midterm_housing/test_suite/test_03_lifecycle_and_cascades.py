"""Non-linear state machines (dispute/revise cycle, confirm/decline branch) and
transitive cascades (damage-approval depth 3, extension-approval depth 2).

Queue A (Difficulty): non_linear_state_machine, transitive_cascade.
Queue B (Corner): state_machines.
"""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    register_host, register_tenant, create_unit, request_booking, confirm_booking,
    register_tenant_with_rejected_verification,
    get_deposit_for_booking, get_payout_for_booking, get_tax_for_booking,
    count_for_booking, setup_completed_booking,
    make_host_headers, make_tenant_headers, TEST_USERS,
)

REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# non_linear_state_machine / damage_claim_dispute_revise_cycle
# --------------------------------------------------------------------------

def _claim_scenario(api):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=150000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirm_booking(api, booking["id"], host["id"])
    deposit = get_deposit_for_booking(api, booking["id"])
    claim = get_success_data(api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": deposit["version"],
         "claimed_cents": 50000, "description": "wall"},
        make_host_headers(host["id"])))
    return host, tenant, claim


def test_damage_claim_dispute_moves_filed_to_disputed(api):
    """PRD §3.8: "The tenant who owns the deposit's booking may dispute it, moving
    `FILED` to `DISPUTED` and recording their `tenant_response`."

    Design: Difficulty/non_linear_state_machine/damage_claim_dispute_revise_cycle
    """
    host, tenant, claim = _claim_scenario(api)
    disputed = get_success_data(api.transition_damage_claim(
        claim["id"], {"to_status": "DISPUTED", "tenant_response": "I dispute"},
        make_tenant_headers(tenant["id"])))
    assert disputed["status"] == "DISPUTED", f"claim must be DISPUTED, got {disputed['status']}"


def test_damage_claim_host_revise_returns_disputed_to_filed(api):
    """PRD §3.8: "The host may answer a dispute by moving `DISPUTED` back to
    `FILED`, revising `claimed_cents` to a new value supplied in the request; this
    `FILED`-to-`DISPUTED`-and-back loop is the cyclic negotiation path."

    Design: Difficulty/non_linear_state_machine/damage_claim_dispute_revise_cycle
    """
    host, tenant, claim = _claim_scenario(api)
    get_success_data(api.transition_damage_claim(
        claim["id"], {"to_status": "DISPUTED", "tenant_response": "I dispute"},
        make_tenant_headers(tenant["id"])))
    revised = get_success_data(api.transition_damage_claim(
        claim["id"], {"to_status": "FILED", "claimed_cents": 30000},
        make_host_headers(host["id"])))
    assert revised["status"] == "FILED", f"claim must return to FILED, got {revised['status']}"
    assert revised["claimed_cents"] == 30000, f"claimed_cents must be revised to 30000, got {revised['claimed_cents']}"


# --------------------------------------------------------------------------
# non_linear_state_machine / booking_confirm_vs_decline_branch
# --------------------------------------------------------------------------

def _branch_scenario(api):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit1 = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=100000)
    unit2 = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=100000)
    booking_a = request_booking(api, unit1["id"], tenant["id"], "2026-06-01", "2026-07-01")
    booking_b = request_booking(api, unit2["id"], tenant["id"], "2026-06-01", "2026-07-01")
    return host, booking_a, booking_b


def test_confirm_branch_spawns_deposit_payout_tax(api):
    """PRD §3.4: "Confirmation sets in motion a rich cascade of created resources."
    PRD §3.4: "A `Deposit` is created for the booking with `amount_cents`
    snapshotted from the unit's `deposit_cents`, all of it placed in `held_cents`,
    with `refunded_cents` and `forfeited_cents` at zero and `status` of `HELD`."
    PRD §3.4: "A `TaxAssessment` is created recording the booking's
    `assessed_term_days` and deriving `taxable`, `occupancy_tax_cents`, and
    `exempt_reason` per the occupancy-tax rule below."

    Design: Difficulty/non_linear_state_machine/booking_confirm_vs_decline_branch
    """
    host, booking_a, booking_b = _branch_scenario(api)
    confirmed = confirm_booking(api, booking_a["id"], host["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert count_for_booking(api, api.list_deposits, booking_a["id"]) == 1, "confirm must spawn exactly one Deposit"
    assert count_for_booking(api, api.list_payouts, booking_a["id"]) == 1, "confirm must spawn exactly one Payout"
    assert count_for_booking(api, api.list_tax_assessments, booking_a["id"]) == 1, "confirm must spawn exactly one TaxAssessment"


def test_decline_branch_spawns_no_children(api):
    """PRD §3.3: "the host who owns the unit may instead reject the request,
    moving `REQUESTED` to the terminal `DECLINED`, also releasing the slot.
    Neither declination nor pre-confirmation cancellation carries any financial
    side effect."

    Design: Difficulty/non_linear_state_machine/booking_confirm_vs_decline_branch
    """
    host, booking_a, booking_b = _branch_scenario(api)
    declined = get_success_data(api.transition_booking(
        booking_b["id"], {"to_status": "DECLINED"}, make_host_headers(host["id"])))
    assert declined["status"] == "DECLINED"
    assert count_for_booking(api, api.list_deposits, booking_b["id"]) == 0, "decline must spawn no Deposit"
    assert count_for_booking(api, api.list_payouts, booking_b["id"]) == 0, "decline must spawn no Payout"
    assert count_for_booking(api, api.list_tax_assessments, booking_b["id"]) == 0, "decline must spawn no TaxAssessment"


# --------------------------------------------------------------------------
# transitive_cascade / damage_approval_depth3_cascade
# --------------------------------------------------------------------------

def _approved_claim_scenario(api):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       utilities_included=False, deposit_cents=150000, monthly_rate_cents=300000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirm_booking(api, booking["id"], host["id"])
    deposit = get_deposit_for_booking(api, booking["id"])
    claim = get_success_data(api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": deposit["version"],
         "claimed_cents": 50000, "description": "carpet"},
        make_host_headers(host["id"])))
    get_success_data(api.transition_damage_claim(
        claim["id"], {"to_status": "APPROVED", "approved_cents": 50000}, REVIEWER))
    return host, booking


def test_damage_approval_hop1_deposit_buckets(api):
    """PRD §3.8: "First, the deposit's `forfeited_cents` increases by
    `approved_cents` and its `held_cents` decreases by the same amount".

    Design: Difficulty/transitive_cascade/damage_approval_depth3_cascade
    """
    host, booking = _approved_claim_scenario(api)
    deposit = get_deposit_for_booking(api, booking["id"])
    assert deposit["forfeited_cents"] == 50000, f"forfeited must be 50000, got {deposit['forfeited_cents']}"
    assert deposit["held_cents"] == 100000, f"held must be 100000, got {deposit['held_cents']}"


def test_damage_approval_hop2_hop3_payout_and_host(api):
    """PRD §3.8: "Second, the related payout's `deposit_adjustment_cents` is set to
    the deposit's `forfeited_cents` and its `net_cents` is recomputed. Third, the
    host's `projected_payout_cents` is recomputed from the updated payout net."

    Design: Difficulty/transitive_cascade/damage_approval_depth3_cascade
    """
    host, booking = _approved_claim_scenario(api)
    payout = get_payout_for_booking(api, booking["id"])
    assert payout["deposit_adjustment_cents"] == 50000, \
        f"deposit_adjustment must be 50000, got {payout['deposit_adjustment_cents']}"
    assert payout["net_cents"] == 314000, f"net must be 300000-36000+50000=314000, got {payout['net_cents']}"
    host_data = get_success_data(api.get_host(host["id"], ADMIN))
    assert host_data["projected_payout_cents"] == 314000, \
        f"host projected must be 314000, got {host_data['projected_payout_cents']}"


# --------------------------------------------------------------------------
# transitive_cascade / extension_approval_depth2_cascade
# --------------------------------------------------------------------------

def _approved_extension_scenario(api):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       deposit_cents=0, monthly_rate_cents=300000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirmed = confirm_booking(api, booking["id"], host["id"])
    ext = get_success_data(api.create_extension(
        {"booking_id": booking["id"], "expected_booking_version": confirmed["version"],
         "new_end_date": "2026-07-16"},
        make_tenant_headers(tenant["id"])))
    get_success_data(api.transition_extension(
        ext["id"], {"to_status": "APPROVED"}, make_host_headers(host["id"])))
    return host, booking


def test_extension_approval_hop1_rewrites_booking(api):
    """PRD §3.7: "the booking's `end_date` is set to `new_end_date`, its
    `term_days` is recomputed, its `rent_cents` and `gross_rent_cents` are
    recomputed on the still-`PROVISIONAL` basis, and its `version` increments by
    one".

    Design: Difficulty/transitive_cascade/extension_approval_depth2_cascade
    """
    host, booking = _approved_extension_scenario(api)
    b = get_success_data(api.get_booking(booking["id"], ADMIN))
    assert b["end_date"] == "2026-07-16", f"end_date must move to 2026-07-16, got {b['end_date']}"
    assert b["term_days"] == 45, f"term_days must be 45, got {b['term_days']}"
    assert b["rent_cents"] == 450000, f"rent must be 450000 (300000*45/30), got {b['rent_cents']}"
    assert b["gross_rent_cents"] == 450000, f"gross must be 450000, got {b['gross_rent_cents']}"


def test_extension_approval_hop2_repays_payout_and_host(api):
    """PRD §3.7: "the related payout's `gross_rent_cents` is reset to the booking's
    new gross, its `net_cents` is recomputed, and the host's
    `projected_payout_cents` is recomputed".

    Design: Difficulty/transitive_cascade/extension_approval_depth2_cascade
    """
    # PRD §3.7 pins that the payout's gross is reset to the booking's new gross
    # and the host's projected earnings are recomputed; it does not state that the
    # platform fee is re-derived on extension (unlike the §3.6 completion cascade),
    # so the fee basis is left open and the absolute net is not asserted here.
    host, booking = _approved_extension_scenario(api)
    payout = get_payout_for_booking(api, booking["id"])
    assert payout["gross_rent_cents"] == 450000, \
        f"payout gross must be reset to the new booking gross 450000, got {payout['gross_rent_cents']}"
    host_data = get_success_data(api.get_host(host["id"], ADMIN))
    # Exactly one PENDING payout exists, so projected_payout_cents == its net (§2.10).
    assert host_data["projected_payout_cents"] == payout["net_cents"], (
        f"host projected ({host_data['projected_payout_cents']}) must equal the sole "
        f"pending payout net ({payout['net_cents']})")


# --------------------------------------------------------------------------
# Corner / state_machines
# --------------------------------------------------------------------------

def test_cancel_completed_booking_returns_invalid_state(api):
    """PRD §2.9: "State legality — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancel_completed_booking_returns_invalid_state
    """
    ctx = setup_completed_booking(api, start_date="2026-02-01", end_date="2026-03-03",
                                  activate_clock=None, complete_clock=None)
    resp = api.transition_booking(
        ctx["booking"]["id"], {"to_status": "CANCELLED"}, make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_verification_resubmit_cycle_restores_pending(api):
    """PRD §3.1: "A tenant whose document was rejected may resubmit it, which moves
    that verification from `REJECTED` back to `PENDING`".
    PRD §3.1: "otherwise, if at least one is `PENDING`, the tenant is `PENDING`".

    Design: Corner/state_machines/verification_resubmit_cycle_restores_pending
    """
    tenant, ver = register_tenant_with_rejected_verification(api)
    resubmitted = get_success_data(api.transition_verification(
        ver["id"], {"to_status": "PENDING"}, make_tenant_headers(tenant["id"])))
    assert resubmitted["status"] == "PENDING", f"verification must return to PENDING, got {resubmitted['status']}"
    tenant_data = get_success_data(api.get_tenant(tenant["id"], REVIEWER))
    assert tenant_data["verification_status"] == "PENDING", \
        f"tenant verification_status must be PENDING, got {tenant_data['verification_status']}"


def test_delist_unit_with_active_booking_rejected(api):
    """PRD §3.2: "the host may permanently retire the unit to the terminal
    `DELISTED` state, but only when the unit carries no booking in `REQUESTED`,
    `CONFIRMED`, or `ACTIVE`; an attempt to delist a unit that still has live
    bookings is rejected with `ERR_UNIT_HAS_ACTIVE_BOOKINGS`."

    Design: Corner/state_machines/delist_unit_with_active_booking_rejected
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=False)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True)
    request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    resp = api.transition_unit(unit["id"], {"to_status": "DELISTED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_HAS_ACTIVE_BOOKINGS)
