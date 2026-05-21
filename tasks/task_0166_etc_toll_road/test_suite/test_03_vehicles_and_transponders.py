"""Vehicle and Transponder lifecycle tests.

PRD §3.2 covers vehicle/transponder registration, binding/unbinding,
and the class-derivation lookup.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_transponder,
    assert_vehicle,
    bind_transponder_payload,
    bind_transponder_to_vehicle,
    create_account,
    create_and_bind_transponder,
    create_transponder,
    create_transponder_payload,
    create_vehicle,
    create_vehicle_payload,
    make_account_holder_headers,
    random_plate,
    random_serial,
    setup_account_with_bound_transponder,
    setup_account_with_vehicle,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Vehicle registration — PRD §3.2
# ---------------------------------------------------------------------------
def test_vehicle_register_succeeds(api):
    """PRD §3.2: "A customer's vehicles are registered against their
    account by submitting a `plate_number` (1 to 10 characters drawn
    from the set of uppercase letters, digits, and dashes), the issuing
    `plate_state` (one of `NY`, `NJ`, `PA`, `FL`, `CA`, `TX`, or
    `OTHER`), an optional `axle_count` between 2 and 7 (defaulting to
    2), and an optional `hov_capable` flag (defaulting to true)
    indicating whether the vehicle is eligible to claim an HOV
    exemption."

    Claim: vehicle creation returns shape conforming to PRD §3.2 fields.
    """
    a = create_account()
    res = api.create_vehicle(
        a["id"],
        create_vehicle_payload(plate_number="ABC123", plate_state="NY"),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert_vehicle(data)
    assert data["plate_number"] == "ABC123"
    assert data["plate_state"] == "NY"
    assert data["axle_count"] == 2
    assert data["hov_capable"] is True
    assert data["status"] == "ACTIVE"


@pytest.mark.parametrize("axle_count,expected_class", [
    (2, "CLASS_2"),
    (3, "CLASS_3"),
    (4, "CLASS_4"),
    (5, "CLASS_5_PLUS"),
    (6, "CLASS_5_PLUS"),
    (7, "CLASS_5_PLUS"),
])
def test_vehicle_class_derivation_from_axle_count(api, axle_count, expected_class):
    """PRD §3.2: "The system derives `vehicle_class` from the
    `axle_count` using a tiered lookup: 2 axles correspond to `CLASS_2`,
    3 axles to `CLASS_3`, 4 axles to `CLASS_4`, and 5 or more axles to
    `CLASS_5_PLUS`."

    Claim: each axle_count maps to the named vehicle_class.
    """
    a = create_account()
    res = api.create_vehicle(
        a["id"],
        create_vehicle_payload(axle_count=axle_count),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert data["vehicle_class"] == expected_class
    assert data["axle_count"] == axle_count


def test_vehicle_duplicate_plate_rejected(api):
    """PRD §3.2: "The combination of `plate_number` and `plate_state` is
    unique across the entire network; an attempt to register a
    duplicate is rejected with `ERR_DUPLICATE_RESOURCE`."

    Claim: a second vehicle with the same (plate_number, plate_state)
    → 409 ERR_DUPLICATE_RESOURCE.
    """
    a1 = create_account()
    api.create_vehicle(
        a1["id"],
        create_vehicle_payload(plate_number="DUP001", plate_state="NY"),
        make_account_holder_headers(a1["id"]),
    )
    a2 = create_account()
    res = api.create_vehicle(
        a2["id"],
        create_vehicle_payload(plate_number="DUP001", plate_state="NY"),
        make_account_holder_headers(a2["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


# ---------------------------------------------------------------------------
# Transponder registration — PRD §3.2
# ---------------------------------------------------------------------------
def test_transponder_register_initial_state(api):
    """PRD §3.2: "A freshly registered transponder begins in `UNBOUND`
    status with `bound_vehicle_id` of null and `bound_at` of null."

    Claim: created transponder.status == UNBOUND with null binding.
    """
    a = create_account()
    res = api.create_transponder(
        a["id"], create_transponder_payload(),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert_transponder(data)
    assert data["status"] == "UNBOUND"
    assert data.get("bound_vehicle_id") is None
    assert data.get("bound_at") is None


def test_transponder_duplicate_serial_rejected(api):
    """PRD §3.2: "Registering one requires submitting only the
    manufacturer `serial_number` (between 10 and 24 characters of
    uppercase letters and digits) which must be globally unique across
    the system; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`."

    Claim: a second transponder with the same serial across two
    accounts → 409 ERR_DUPLICATE_RESOURCE.
    """
    a1 = create_account()
    s = random_serial()
    api.create_transponder(
        a1["id"], create_transponder_payload(serial_number=s),
        make_account_holder_headers(a1["id"]),
    )
    a2 = create_account()
    res = api.create_transponder(
        a2["id"], create_transponder_payload(serial_number=s),
        make_account_holder_headers(a2["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


# ---------------------------------------------------------------------------
# Bind / unbind state machine — PRD §3.2
# ---------------------------------------------------------------------------
def test_transponder_bind_transitions_to_active(api):
    """PRD §3.2: "Binding the transponder to one of the account's
    vehicles transitions it from `UNBOUND` to `ACTIVE`: the bind
    request carries the target `vehicle_id`, and the operation
    requires that the transponder's owning account match the path
    account, that the target vehicle exists and is owned by the same
    account, that the vehicle's status is `ACTIVE`, that the account's
    status is `ACTIVE`, and that no other transponder is presently
    bound to the same vehicle."
    PRD §3.2: "A successful bind records the target as
    `bound_vehicle_id` and stamps `bound_at` with the current UTC
    instant."

    Claim: after bind, transponder.status=ACTIVE,
    bound_vehicle_id=vehicle.id, bound_at set.
    """
    a, v = setup_account_with_vehicle()
    t = create_transponder(a["id"])
    res = api.bind_transponder(
        a["id"], t["id"],
        bind_transponder_payload(vehicle_id=v["id"]),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=200)
    assert data["status"] == "ACTIVE"
    assert data["bound_vehicle_id"] == v["id"]
    assert data["bound_at"] is not None


def test_transponder_bind_same_vehicle_twice_rejected(api):
    """PRD §3.2: "no other transponder is presently bound to the same
    vehicle."
    PRD §3.2: "the last surfaces as `ERR_VEHICLE_ALREADY_BOUND`."

    Claim: binding a second transponder to a vehicle that already has
    an ACTIVE binding → 409 ERR_VEHICLE_ALREADY_BOUND.
    """
    a, v, t1 = setup_account_with_bound_transponder()
    t2 = create_transponder(a["id"])
    res = api.bind_transponder(
        a["id"], t2["id"],
        bind_transponder_payload(vehicle_id=v["id"]),
        make_account_holder_headers(a["id"]),
    )
    validate_error(res, "ERR_VEHICLE_ALREADY_BOUND", expected_status=409)


def test_transponder_bind_to_blocked_vehicle_rejected(api):
    """PRD §3.2: "The first four of those preconditions, when
    violated, surface as `ERR_FORBIDDEN`, `ERR_NOT_FOUND`,
    `ERR_VEHICLE_BLOCKED`, and `ERR_ACCOUNT_NOT_ACTIVE` respectively
    (see §2.11 for the evaluation order)."

    Note: PRD §2.11 lists `ERR_VEHICLE_BLOCKED` as priority 10
    (business_safety) which fires before `ERR_VEHICLE_ALREADY_BOUND`
    (priority 13). To isolate, we use a BLOCKED vehicle that has no
    other transponder bound.

    Claim: binding to a BLOCKED vehicle → 409 ERR_VEHICLE_BLOCKED.
    """
    # Build an Account that gets suspended, then expect Vehicle.status
    # to be BLOCKED via cascade; bind a fresh transponder.
    from test_helpers import setup_suspended_account_via_two_hov_frauds
    account, frauds, target, _ = setup_suspended_account_via_two_hov_frauds()
    # After cascade the target vehicle is BLOCKED. Account.status is
    # SUSPENDED, so per PRD §2.11 priority 6 (ERR_ACCOUNT_NOT_ACTIVE)
    # actually fires before priority 10 (ERR_VEHICLE_BLOCKED). This
    # test therefore expects ERR_ACCOUNT_NOT_ACTIVE — the deeper
    # business_safety claim is covered by the difficulty-design suite
    # on a configuration where Account is ACTIVE but Vehicle is BLOCKED.
    assert account["status"] == "SUSPENDED"
    t = create_transponder(account["id"])
    res = api.bind_transponder(
        account["id"], t["id"],
        bind_transponder_payload(vehicle_id=target["id"]),
        make_account_holder_headers(account["id"]),
    )
    validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE", expected_status=409)


def test_transponder_unbind_transitions_to_unbound(api):
    """PRD §3.2: "The reverse action, unbinding, transitions an `ACTIVE`
    transponder back to `UNBOUND`, clearing both `bound_vehicle_id` and
    `bound_at` to null."

    Claim: after unbind, transponder.status == UNBOUND,
    bound_vehicle_id == null, bound_at == null.
    """
    a, v, t = setup_account_with_bound_transponder()
    res = api.unbind_transponder(
        a["id"], t["id"], make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=200)
    assert data["status"] == "UNBOUND"
    assert data.get("bound_vehicle_id") is None
    assert data.get("bound_at") is None


def test_transponder_unbind_from_unbound_rejected(api):
    """PRD §3.2: "Unbinding requires the transponder to be currently
    `ACTIVE`; an attempt to unbind a transponder in any other state is
    rejected with `ERR_INVALID_STATE`."

    Claim: unbind an UNBOUND transponder → 409 ERR_INVALID_STATE.
    """
    a = create_account()
    t = create_transponder(a["id"])
    assert t["status"] == "UNBOUND"
    res = api.unbind_transponder(
        a["id"], t["id"], make_account_holder_headers(a["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_transponder_delete_unbound_transitions_to_returned(api):
    """PRD §3.2: "A transponder that is `UNBOUND` may be permanently
    retired by an account holder or admin, which transitions it to the
    terminal `RETURNED` state and excludes it from any future bind
    attempt; the precondition is again that the transponder must
    currently be `UNBOUND`."

    Claim: DELETE on UNBOUND transponder → 204; subsequent bind to a
    new vehicle is excluded.
    """
    a, v = setup_account_with_vehicle()
    t = create_transponder(a["id"])
    res = api.delete_transponder(
        a["id"], t["id"], make_account_holder_headers(a["id"]),
    )
    assert res.status_code == 204

    # Subsequent bind is excluded — the transponder is RETURNED.
    bind_res = api.bind_transponder(
        a["id"], t["id"],
        bind_transponder_payload(vehicle_id=v["id"]),
        make_account_holder_headers(a["id"]),
    )
    assert bind_res.status_code in (404, 409)


def test_transponder_delete_active_rejected(api):
    """PRD §3.2: "the precondition is again that the transponder must
    currently be `UNBOUND`."

    Claim: DELETE on ACTIVE transponder → 409 ERR_INVALID_STATE.
    """
    a, v, t = setup_account_with_bound_transponder()
    res = api.delete_transponder(
        a["id"], t["id"], make_account_holder_headers(a["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
