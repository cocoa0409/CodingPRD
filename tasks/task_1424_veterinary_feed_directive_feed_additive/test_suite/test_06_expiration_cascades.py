"""Expiration boundaries and cascades: VFD expiration exact boundary,
vet-suspension transitive cascade, veterinarian state cycle, terminal-state
revocation guard (PRD §2.4, §2.5, §3.4, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS, api_client,
    setup_clinic_with_vet, setup_order_chain, setup_validated_order,
    submit_order, validate_order, fresh_vfd, set_clock,
    make_veterinarian_headers, make_feed_mill_operator_headers,
)

INSPECTOR = TEST_USERS["inspector_headers"]

VFD_EXPIRATION = "2026-10-01T00:00:00Z"


# ─── Difficulty: vfd_expiration_exact_boundary ───

def test_validate_succeeds_one_second_before_expiration_and_fails_at_expiration(api):
    """PRD §3.5: "Second, the logical clock must be strictly before the VFD's
    `expiration_date` (otherwise `ERR_VFD_EXPIRED`, HTTP 409)."

    At expiration - 1s validation succeeds; at the exact expiration instant the
    strict inequality fails and validation is rejected (HTTP 409). The PRD pins
    the rejection but leaves which of the VFD guards reports it at that instant
    (§2.5 drives the status cascade for expiration dates "now in the past"), so
    any VFD-side 409 guard error satisfies the boundary claim.

    Design: Difficulty/boundary_precision_check/vfd_expiration_exact_boundary
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 30, "expiration_date": VFD_EXPIRATION},
        order_overrides={"animal_count": 5},
    )
    # One second before expiration: all eight validation checks pass.
    set_clock("2026-09-30T23:59:59Z")
    validated = validate_order(chain["mill"], chain["order"], chain["vfd"]["id"])
    assert validated["status"] == "VALIDATED"

    order2 = submit_order(chain["mill"], chain["vfd"], chain["producer"], animal_count=5)
    # Exactly at expiration: the strict-before guard fails.
    set_clock(VFD_EXPIRATION)
    res = api.validate_feed_order(
        order2["id"],
        {"expected_vfd_authorization_version": fresh_vfd(chain["vfd"]["id"])["version"]},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    )
    assert res.status_code == 409, f"Expected 409 at expiration boundary, got {res.status_code}"
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_VFD_EXPIRED.value,
        ApiErrorId.ERR_VFD_NOT_USABLE.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])


def test_vfd_transitions_to_expired_once_expiration_is_in_the_past(api):
    """PRD §2.5: "Advancing the clock re-evaluates two families of time-driven
    state transitions: any `VfdAuthorization` whose `expiration_date` is now in
    the past transitions to `EXPIRED`, and any `VcpVerification` whose
    `expires_on` is now in the past transitions to `EXPIRED`."

    Design: Difficulty/boundary_precision_check/vfd_expiration_exact_boundary
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 30, "expiration_date": VFD_EXPIRATION},
        order_overrides={"animal_count": 5},
    )
    set_clock("2026-10-01T00:00:01Z")  # one second past expiration
    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["status"] == "EXPIRED", (
        f"VFD must be EXPIRED once expiration_date is in the past, got {vfd_after['status']}"
    )


# ─── Difficulty: vet_suspend_cascades_to_vfd_to_feedorder_to_mill ───

def _setup_validated_then_suspend_vet():
    """Validated order against the vet's VFD, then the inspector suspends the vet."""
    chain = setup_validated_order(
        vfd_overrides={"authorized_animal_count": 40},
        order_overrides={"animal_count": 8},
    )
    vet = validate_success(
        api_client.suspend_veterinarian(chain["vet"]["id"], INSPECTOR), 200,
    )
    return chain, vet


def test_vet_suspend_cascades_vfd_expiry_and_order_cancellation(api):
    """PRD §3.4: "Suspending a veterinarian who is currently `ACTIVE` moves the
    veterinarian to `SUSPENDED` (any other starting state is rejected with
    `ERR_INVALID_STATE`) and fires the cascade above across every
    `VfdAuthorization` in `ISSUED` or `PARTIALLY_USED` issued by that
    veterinarian."
    PRD §3.4: "every `FeedOrder` for this VFD currently in `SUBMITTED` or
    `VALIDATED` transitions to `CANCELLED` with its `rejection_reason` set to the
    string `VFD_EXPIRED`"

    Design: Difficulty/transitive_cascade/vet_suspend_cascades_to_vfd_to_feedorder_to_mill
    """
    chain, vet = _setup_validated_then_suspend_vet()
    assert vet["status"] == "SUSPENDED"

    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["status"] == "EXPIRED", (
        f"Cascade hop 1 (VFD -> EXPIRED) failed, got {vfd_after['status']}"
    )
    order_after = validate_success(api.get_feed_order(chain["order"]["id"], INSPECTOR), 200)
    assert order_after["status"] == "CANCELLED", (
        f"Cascade hop 2 (order -> CANCELLED) failed, got {order_after['status']}"
    )
    assert order_after.get("rejection_reason") == "VFD_EXPIRED"


def test_vet_suspend_cascade_restores_quota_and_mill_pending_count(api):
    """PRD §3.4: "the owning `FeedMill`'s `pending_order_count` is decremented
    once for each order that was in `VALIDATED` when it was cancelled"
    PRD §3.4: "The compensating quota return described in §2.8 also fires for
    each cancelled validated order."

    Design: Difficulty/transitive_cascade/vet_suspend_cascades_to_vfd_to_feedorder_to_mill
    """
    chain, _ = _setup_validated_then_suspend_vet()

    mill_after = validate_success(api.get_feed_mill(chain["mill"]["id"], INSPECTOR), 200)
    assert mill_after["pending_order_count"] == 0, (
        f"Cascade hop 3 (mill pending decremented) failed, got {mill_after['pending_order_count']}"
    )
    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["remaining_animal_count"] == 40, (
        f"Compensating return must restore remaining to 40, got {vfd_after['remaining_animal_count']}"
    )


# ─── Difficulty: veterinarian_active_suspended_active_cycle ───

def test_veterinarian_suspend_reinstate_cycle_reenters_active(api):
    """PRD §3.4: "Suspending a veterinarian who is currently `ACTIVE` moves the
    veterinarian to `SUSPENDED` (any other starting state is rejected with
    `ERR_INVALID_STATE`) and fires the cascade above across every
    `VfdAuthorization` in `ISSUED` or `PARTIALLY_USED` issued by that
    veterinarian."
    PRD §3.4: "Reinstating a `SUSPENDED` veterinarian returns them to `ACTIVE`
    but does not resurrect any expired VFDs — the veterinarian must re-issue new
    authorizations."

    Design: Difficulty/non_linear_state_machine/veterinarian_active_suspended_active_cycle
    """
    _, vet = setup_clinic_with_vet()
    suspended = validate_success(api.suspend_veterinarian(vet["id"], INSPECTOR), 200)
    assert suspended["status"] == "SUSPENDED"
    reinstated = validate_success(api.reinstate_veterinarian(vet["id"], INSPECTOR), 200)
    assert reinstated["status"] == "ACTIVE"


def test_veterinarian_cycle_twice_increments_version_per_mutation(api):
    """PRD §3.4: "Reinstating a `SUSPENDED` veterinarian returns them to `ACTIVE`"
    PRD §2.4: "a `version` integer that starts at 1 and increments on every
    mutation."

    Four transitions (suspend, reinstate, suspend, reinstate) from the initial
    version 1 yield version 5, proving the cycle re-enters ACTIVE repeatedly.

    Design: Difficulty/non_linear_state_machine/veterinarian_active_suspended_active_cycle
    """
    _, vet = setup_clinic_with_vet()
    assert vet["version"] == 1
    for _ in range(2):
        validate_success(api.suspend_veterinarian(vet["id"], INSPECTOR), 200)
        validate_success(api.reinstate_veterinarian(vet["id"], INSPECTOR), 200)
    vet_after = validate_success(api.get_veterinarian(vet["id"], INSPECTOR), 200)
    assert vet_after["status"] == "ACTIVE"
    assert vet_after["version"] == 5, (
        f"Expected version 5 (1 initial + 4 transitions), got {vet_after['version']}"
    )


# ─── Corner: revoke_terminal_vfd_returns_invalid_state ───

def test_revoke_expired_vfd_returns_invalid_state(api):
    """PRD §3.4: "it can be revoked by the veterinarian who issued it, which
    requires `X-User-ID` to equal the VFD's `vet_id` (otherwise `ERR_FORBIDDEN`)
    and requires current status `ISSUED` or `PARTIALLY_USED` (otherwise
    `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/revoke_terminal_vfd_returns_invalid_state
    """
    chain = setup_order_chain(
        vfd_overrides={"expiration_date": "2026-09-01T00:00:00Z"},
    )
    set_clock("2026-09-02T00:00:00Z")  # expiration is now in the past
    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["status"] == "EXPIRED"

    res = api.revoke_vfd_authorization(
        chain["vfd"]["id"], make_veterinarian_headers(chain["vet"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
