"""Parallel case_status/hold_status axes, depth-4 payment cascade, dispute de-escalation
cascade, and hold placement/release guards.

Covers difficulty rules non_linear_state_machine (scofflaw_case_parallel_status_hold),
transitive_cascade (payment_resolves_case_releases_hold, dispute_deescalates_cancels_boot),
plus corner state machines (double_place_hold, release_hold_without_hold).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_owner_vehicle_case, setup_case_with_violations,
    file_violation, file_dispute, dispatch_boot, get_case, make_owner_headers,
)

EO = TEST_USERS["enforcement_officer_headers"]
COLLECTIONS = TEST_USERS["collections_admin_headers"]


# ─── non_linear_state_machine / scofflaw_case_parallel_status_hold ─────────

def _scofflaw_case_hold_placed(api):
    owner, vehicle, case, _ = setup_case_with_violations(5, 12000)  # collectible 60000, count 5
    placed = validate_success(api.place_hold(case["id"], EO), 200)
    return owner, vehicle, case, placed


def test_place_hold_advances_hold_axis_independently(api):
    """PRD §3.7: "Placing moves hold_status to HOLD_PLACED, sets the vehicle's hold_flag
    to true, and increments the case's version;"

    Design: Difficulty/non_linear_state_machine/scofflaw_case_parallel_status_hold
    """
    _, _, _, placed = _scofflaw_case_hold_placed(api)
    assert placed["hold_status"] == "HOLD_PLACED"
    assert placed["case_status"] == "SCOFFLAW"


def test_place_hold_sets_vehicle_hold_flag(api):
    """PRD §3.7: "Placing moves hold_status to HOLD_PLACED, sets the vehicle's hold_flag
    to true, and increments the case's version;"

    Design: Difficulty/non_linear_state_machine/scofflaw_case_parallel_status_hold
    """
    _, vehicle, _, _ = _scofflaw_case_hold_placed(api)
    fresh = validate_success(api.get_vehicle(vehicle["id"], EO), 200)
    assert fresh["hold_flag"] is True


# ─── transitive_cascade / payment_resolves_case_releases_hold ──────────────

def _paid_off_held_case(api):
    """SCOFFLAW case (one 50000 citation), hold placed, then a 50000 payment applied."""
    owner, vehicle, case, violations = setup_case_with_violations(
        1, 50000, violation_type="FIRE_HYDRANT")
    validate_success(api.place_hold(case["id"], EO), 200)
    validate_success(api.create_payment(
        case["id"], {"amount_cents": 50000, "method": "CARD"},
        make_owner_headers(owner["id"])), 201)
    return owner, vehicle, case, violations[0]


def test_final_payment_resolves_case(api):
    """PRD §3.4: "A case reaches RESOLVED (SCOFFLAW → RESOLVED) when its collectible
    balance falls to exactly 0 and no enforcement order on the case is still DISPATCHED or
    APPLIED."

    Design: Difficulty/transitive_cascade/payment_resolves_case_releases_hold
    """
    _, _, case, violation = _paid_off_held_case(api)
    assert validate_success(api.get_violation(violation["id"], EO), 200)["status"] == "PAID"
    fresh = get_case(case["id"])
    assert fresh["collectible_balance_cents"] == 0
    assert fresh["case_status"] == "RESOLVED"


def test_resolution_releases_hold_and_clears_flag(api):
    """PRD §3.4: "Resolution is where the four-step cascade lands: the final payment
    resolves the case, and if that case is currently HOLD_PLACED, the resolution releases
    the registration hold (hold_status → HOLD_RELEASED) and clears the vehicle's hold_flag."

    Design: Difficulty/transitive_cascade/payment_resolves_case_releases_hold
    """
    _, vehicle, case, _ = _paid_off_held_case(api)
    assert get_case(case["id"])["hold_status"] == "HOLD_RELEASED"
    assert validate_success(api.get_vehicle(vehicle["id"], EO), 200)["hold_flag"] is False


# ─── transitive_cascade / dispute_deescalates_cancels_boot ─────────────────

def _deescalated_case_with_boot(api):
    """4 x 8000 + 1 x 20000 -> SCOFFLAW boot-eligible; BOOT dispatched; then the 20000
    citation is disputed, dropping collectible to 32000 and de-escalating the case."""
    owner, vehicle, case, _ = setup_case_with_violations(4, 8000)
    vbig = file_violation(case["id"], fine_amount_cents=20000, violation_type="NO_PERMIT")
    order = dispatch_boot(case["id"])
    file_dispute(vbig["id"], owner["id"])
    return case, vbig, order


def test_dispute_deescalates_case_to_compliant(api):
    """PRD §3.3: "the violation's current due drops out of the collectible view (see §3.4),
    which can de-escalate the case out of SCOFFLAW and cancel any still-pending enforcement
    order."

    Design: Difficulty/transitive_cascade/dispute_deescalates_cancels_boot
    """
    case, vbig, _ = _deescalated_case_with_boot(api)
    assert validate_success(api.get_violation(vbig["id"], EO), 200)["status"] == "DISPUTED"
    fresh = get_case(case["id"])
    assert fresh["collectible_balance_cents"] == 32000
    assert fresh["case_status"] == "COMPLIANT"


def test_deescalation_cancels_dispatched_boot(api):
    """PRD §3.6: "the system performs this same cancellation automatically on any
    still-DISPATCHED order when a case de-escalates out of SCOFFLAW."

    Design: Difficulty/transitive_cascade/dispute_deescalates_cancels_boot
    """
    _, _, order = _deescalated_case_with_boot(api)
    assert validate_success(api.get_boot_tow_order(order["id"], EO), 200)["status"] == "CANCELLED"


# ─── corner: double place-hold / release without hold ──────────────────────

def test_double_place_hold_rejected(api):
    """PRD §3.7: "a hold placed while one is already active is rejected with
    ERR_HOLD_ALREADY_PLACED (HTTP 409)."

    Design: Corner/state_machines/double_place_hold_rejected
    """
    _, _, case, _ = setup_case_with_violations(5, 12000)
    validate_success(api.place_hold(case["id"], EO), 200)
    res = api.place_hold(case["id"], EO)
    validate_error(res, "ERR_HOLD_ALREADY_PLACED", expected_status=409)


def test_release_hold_without_hold_rejected(api):
    """PRD §3.7: "Releasing a hold — permitted to a collections administrator or an
    enforcement officer, with an optional release_reason — requires hold_status to be
    HOLD_PLACED; a release attempted otherwise is rejected with ERR_NO_HOLD_TO_RELEASE
    (HTTP 409)."

    Design: Corner/state_machines/release_hold_without_hold_rejected
    """
    _, _, case = setup_owner_vehicle_case()
    file_violation(case["id"], fine_amount_cents=10000)
    file_violation(case["id"], fine_amount_cents=10000)  # COMPLIANT, NO_HOLD
    res = api.release_hold(case["id"], COLLECTIONS, {"release_reason": "MANUAL"})
    validate_error(res, "ERR_NO_HOLD_TO_RELEASE", expected_status=409)
