"""State-machine corner claims: initial states, precondition enforcement,
terminal lockdown, invalid transitions, and clock-driven transitions
(PRD §2.4, §3.3, §3.4, §3.5, §3.6, §3.7, §3.8, §3.9).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, create_holder,
    create_vehicle, create_draft_registration, create_insurance,
    finalize_inspection_for_registration, deposit, get_holder, set_clock,
    setup_active_registration, setup_route, setup_route_pass,
    setup_fleet_scenario, setup_dispatch,
    create_violation_payload,
    assert_instant_equal,
    COMMUNITY_ADMIN, OFFICER,
    ApiErrorId,
)


def test_registration_initial_state_draft():
    """PRD §3.3: "A new registration starts in `DRAFT`. Creation computes the
    provisional annual fee from the declared equipment (the PROVISIONAL variant of
    §3.5) and stores it in `provisional_fee_cents`. The remaining fiscal fields
    settle into their initial state: `finalized_fee_cents` is null until an
    inspection passes (or a late renewal recomputes it), `late_fee_cents` is zero,
    `total_due_cents` starts at zero and is populated once the finalized fee first
    exists, `paid_cents` is zero, both `renewal_score_provisional` and
    `renewal_score_audited` are null, and `valid_from` and `expiry_date` are null
    until first activation."

    Design: Corner/state_machines/registration_initial_state_draft
    """
    community = create_community(name="C-INIT")
    holder = create_eligible_holder(community["id"], full_name="H INIT",
                                    birth_date="2010-05-01")
    vehicle = create_vehicle(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    assert registration["status"] == "DRAFT"
    assert registration["finalized_fee_cents"] is None
    # Default factory cart: headlights + brake_lights only -> equipment_count 2.
    # PRD §3.5 PROVISIONAL: mult = 1 + 0.02*2 = 1.04; 7500 * 1.04 = 7800;
    # 4 seats -> no surcharge; fleet program disabled by default -> no discount;
    # fee = max(7800, 7500) = 7800.
    assert registration["provisional_fee_cents"] == 7800


def test_activate_draft_without_inspection_rejected():
    """PRD §3.5: "It is gated on the full compliance picture: the most recently
    finalized inspection for the registration must be `PASSED` (otherwise
    `ERR_INSPECTION_NOT_PASSED`, HTTP 422); when the community's
    `insurance_required` is true, an `ACTIVE` policy must cover the registration's
    vehicle (otherwise `ERR_INSURANCE_MISSING`, HTTP 422); the holder must be
    `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`, HTTP 422) and must not be
    `BARRED` (otherwise `ERR_HOLDER_BARRED`, HTTP 422)"

    Design: Corner/state_machines/activate_draft_without_inspection_rejected
    """
    community = create_community(name="C-PRE")
    holder = create_eligible_holder(community["id"], full_name="H PRE",
                                    birth_date="2010-05-01")
    vehicle = create_vehicle(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    create_insurance(holder["id"], vehicle["id"], policy_number="N-PRE")
    hh = make_permit_holder_headers(holder["id"])
    res = api_client.activate_registration(registration["id"], hh)
    validate_error(res, ApiErrorId.ERR_INSPECTION_NOT_PASSED, expected_status=422)
    reg_after = get_success_data(
        api_client.get_registration(registration["id"], COMMUNITY_ADMIN))
    assert reg_after["status"] == "DRAFT"


def test_revoked_registration_is_terminal():
    """PRD §3.6: "An `EnforcementOfficer` may revoke a registration in `ACTIVE`,
    `RENEWAL_PENDING`, `SUSPENDED`, or `EXPIRED` status; `REVOKED` is terminal, and
    revocation from any of the first three states revokes the registration's
    `ACTIVE` route passes."
    PRD §2.6: "**State and concurrency** — the target resource's own state machine
    permits the requested transition from its current state, and any OCC version
    field matches the stored version. A state-machine failure is rejected with
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/revoked_registration_is_terminal
    """
    ctx = setup_active_registration(
        community_name="C-TERM", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-TERM"})
    holder = ctx["holder"]
    reg = ctx["registration"]
    validate_success(api_client.revoke_registration(reg["id"], OFFICER), 200)
    # Move the clock inside what would have been the renewal window.
    set_clock("2027-03-15T00:00:00Z")
    hh = make_permit_holder_headers(holder["id"])
    res = api_client.renew_registration(reg["id"], hh)
    # No transition out of REVOKED exists.
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_dismiss_dismissed_violation_rejected():
    """PRD §3.9: "Dismissing moves a violation from either `FILED` or `UPHELD` to
    `DISMISSED` — dismissing an `UPHELD` violation is the appeal path — and when
    the dismissed violation had been `UPHELD`, the holder's `points_balance` and
    `compliance_status` are recomputed downward. A dismissal never reinstates
    registrations on its own: holders who drop out of `BARRED` must have each
    suspended registration reinstated individually. Both `UPHELD` and `DISMISSED`
    are terminal states for the violation itself."

    Design: Corner/state_machines/dismiss_dismissed_violation_rejected
    """
    community = create_community(name="C-INV")
    holder = create_holder(community["id"], full_name="H INV",
                           birth_date="2010-05-01")
    vio = get_success_data(api_client.create_violation(
        create_violation_payload(holder["id"], violation_code="PARKING_VIOLATION",
                                 points_assessed=3, fine_cents=2000,
                                 occurred_at="2026-04-15T00:00:00Z"), OFFICER))
    validate_success(api_client.dismiss_violation(vio["id"], OFFICER), 200)
    res = api_client.dismiss_violation(vio["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    vio_after = get_success_data(api_client.get_violation(vio["id"], OFFICER))
    assert vio_after["status"] == "DISMISSED"
    assert get_holder(holder["id"])["points_balance"] == 0


def test_route_pass_completes_via_clock():
    """PRD §3.7: "A pass whose window runs its course completes when the clock
    reaches its `end_at` (`ACTIVE` → `COMPLETED`), and a pass caught by any cascade
    of §2.11 flips to `REVOKED`."
    PRD §2.4: "a route pass in `ACTIVE` flips to `COMPLETED` when the clock reaches
    its `end_at`"

    Design: Corner/state_machines/route_pass_completes_via_clock
    """
    ctx = setup_active_registration(
        community_name="C-CLK1", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-CLK1"})
    holder = ctx["holder"]
    reg = ctx["registration"]
    route = setup_route(ctx["community"]["id"], name="R-CLK1",
                        route_type="STREET", allowed_vehicle_class="LSV_ALLOWED")
    rp = setup_route_pass(route["id"], reg["id"], holder["id"],
                          start_at="2026-05-01T10:00:00Z",
                          end_at="2026-05-01T12:00:00Z")
    set_clock("2026-05-01T13:00:00Z")
    rp_after = get_success_data(api_client.get_route_pass(rp["id"], COMMUNITY_ADMIN))
    # now 13:00 >= end_at 12:00 -> COMPLETED.
    assert rp_after["status"] == "COMPLETED"


def test_registration_expires_via_clock():
    """PRD §2.4: "a registration in `ACTIVE` flips to `EXPIRED` once the clock
    moves past its `expiry_date`"
    PRD §3.5: "On success the wallet is debited by `total_due_cents`, the
    registration's `paid_cents` accumulates that same amount, `valid_from` is set
    to the activation instant, `expiry_date` is set 365 days after `valid_from`,
    and both the registration's and the holder's `version` increment by 1."

    Design: Corner/state_machines/registration_expires_via_clock
    """
    ctx = setup_active_registration(
        community_name="C-CLK2", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-CLK2"})
    reg = ctx["registration"]
    # valid_from 2026-05-01T00:00:00Z + 365 days (PRD §3.5); instant comparison
    # because PRD pins the instant, not the serialization of expiry_date.
    assert_instant_equal(reg["expiry_date"], "2027-05-01T00:00:00Z")
    set_clock("2027-05-02T00:00:00Z")
    reg_after = get_success_data(
        api_client.get_registration(reg["id"], COMMUNITY_ADMIN))
    assert reg_after["status"] == "EXPIRED"


def test_insurance_expiry_blocks_activation():
    """PRD §2.4: "an insurance policy in `ACTIVE` flips to `EXPIRED` once the
    current date is later than its `expiry_date` (the expiry date itself is the
    last covered day)."
    PRD §3.5: "when the community's `insurance_required` is true, an `ACTIVE`
    policy must cover the registration's vehicle (otherwise
    `ERR_INSURANCE_MISSING`, HTTP 422)"

    Design: Corner/state_machines/insurance_expiry_blocks_activation
    """
    community = create_community(name="C-INS")
    holder = create_eligible_holder(community["id"], full_name="H INS",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 100000, holder["version"])
    vehicle = create_vehicle(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"],
                                             registration_year=2026)
    finalize_inspection_for_registration(registration["id"], score=90)
    policy = create_insurance(holder["id"], vehicle["id"], policy_number="N-INS",
                              effective_date="2026-01-01", expiry_date="2026-06-01")
    set_clock("2026-06-02T00:00:00Z")
    pol_after = get_success_data(
        api_client.get_insurance_policy(policy["id"], COMMUNITY_ADMIN))
    assert pol_after["status"] == "EXPIRED"
    hh = make_permit_holder_headers(holder["id"])
    res = api_client.activate_registration(registration["id"], hh)
    validate_error(res, ApiErrorId.ERR_INSURANCE_MISSING, expected_status=422)
    reg_after = get_success_data(
        api_client.get_registration(registration["id"], COMMUNITY_ADMIN))
    assert reg_after["status"] == "DRAFT"
    assert get_holder(holder["id"])["wallet_balance_cents"] == 100000


def test_overdue_dispatch_return_charges_late_fine():
    """PRD §3.8: "If the clock moves past `shift_end` while the vehicle is still
    out, the dispatch flips to `OVERDUE`. The holder returns the vehicle from
    either `CHECKED_OUT` or `OVERDUE`: the dispatch records `returned_at` at the
    return instant and moves to `RETURNED` (terminal), the vehicle flips back to
    `AVAILABLE`, the community's `checked_out_count` drops by 1, and when the
    return is later than `shift_end` a late fine is computed — the number of days
    late with any partial day rounded up, multiplied by 500 cents — and recorded in
    `late_fine_cents` and debited from the holder's wallet."
    PRD §2.4: "a fleet dispatch in `CHECKED_OUT` flips to `OVERDUE` once the clock
    moves past its `shift_end`"

    Design: Corner/state_machines/overdue_dispatch_return_charges_late_fine
    """
    ctx = setup_fleet_scenario(community_name="C-LATE", slot_count=1, rate=10)
    holder = ctx["holder"]
    holder = deposit(holder["id"], 5000, holder["version"])
    dispatch = setup_dispatch(ctx["fleet_vehicle"]["id"], holder["id"],
                              shift_start="2026-05-01T09:00:00Z",
                              shift_end="2026-05-02T00:00:00Z")
    set_clock("2026-05-01T10:00:00Z")
    hh = make_permit_holder_headers(holder["id"])
    validate_success(api_client.checkout_fleet_dispatch(dispatch["id"], hh), 200)
    set_clock("2026-05-03T12:00:00Z")
    mid = get_success_data(
        api_client.get_fleet_dispatch(dispatch["id"], COMMUNITY_ADMIN))
    assert mid["status"] == "OVERDUE"  # 2026-05-03T12:00 > shift_end 2026-05-02
    returned = validate_success(
        api_client.return_fleet_dispatch(dispatch["id"], hh), 200)
    assert returned["status"] == "RETURNED"
    # ceil(1.5 days) * 500 = 1000.
    assert returned["late_fine_cents"] == 1000
    assert get_holder(holder["id"])["wallet_balance_cents"] == 4000
    community = get_success_data(
        api_client.get_community(ctx["community"]["id"], COMMUNITY_ADMIN))
    assert community["checked_out_count"] == 0
