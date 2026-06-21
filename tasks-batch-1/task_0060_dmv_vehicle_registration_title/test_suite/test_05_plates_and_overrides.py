"""License plate assignment/toggling, registration overrides, and their cascades."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    create_owner,
    create_verified_vehicle,
    issue_clear_title,
    create_registration,
    assess_and_pay_fees,
    assign_plate,
    setup_active_registration,
    setup_active_registration_with_plate,
)

CLERK = TEST_USERS["clerk_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _active_reg_on_new_vehicle(plate_suffix, clock="2026-06-01T00:00:00Z"):
    """Helper: build an ACTIVE registration on a fresh emissions-exempt vehicle.
    Returns (owner, vehicle, registration)."""
    return setup_active_registration(model_year=2008, clock=clock)


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/suspend_cascades_electronic_plate_deactivation
# ---------------------------------------------------------------------------
def test_suspend_deactivates_active_electronic_plate():
    """PRD §3.8: "Suspending an `ACTIVE` registration, advancing it `ACTIVE → SUSPENDED` (the
    registration must be `ACTIVE`, otherwise `ERR_INVALID_STATE`, HTTP 409), transitions every
    electronic plate of that registration currently in status `ACTIVE` to `DEACTIVATED` and
    increments the registration's `version` by 1."

    Design: Difficulty/transitive_cascade/suspend_cascades_electronic_plate_deactivation
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="ELECTRONIC", plate_number="ELEC-0050", activate_plate=True
    )
    assert plate["status"] == "ACTIVE"
    suspended = validate_success(api_client.suspend_registration(reg["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    plate_after = validate_success(api_client.get_license_plate(plate["id"], CLERK), 200)
    assert plate_after["status"] == "DEACTIVATED"


def test_suspend_sets_registration_suspended():
    """PRD §3.8: "Suspending an `ACTIVE` registration, advancing it `ACTIVE → SUSPENDED` ...
    transitions every electronic plate of that registration currently in status `ACTIVE` to
    `DEACTIVATED`".

    Hop-1 of the cascade in isolation: the suspend itself moves the registration to SUSPENDED
    (the precondition that causes the hop-2 plate deactivation).

    Design: Difficulty/transitive_cascade/suspend_cascades_electronic_plate_deactivation
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="ELECTRONIC", plate_number="ELEC-0051", activate_plate=True
    )
    suspended = validate_success(api_client.suspend_registration(reg["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/suspend_reinstate_conserves_active_electronic_plate_count
# ---------------------------------------------------------------------------
def test_suspend_then_reinstate_reactivates_electronic_plate():
    """PRD §3.8: "Reinstating a `SUSPENDED` registration, advancing it `SUSPENDED → ACTIVE`, is
    guarded by optimistic concurrency: it requires `expected_registration_version` matching the
    registration's current `version` ... on success it transitions every electronic plate of
    that registration currently in status `DEACTIVATED` back to `ACTIVE` and increments the
    registration's `version` by 1."

    Suspend (deactivate) then reinstate (reactivate) returns the electronic plate to ACTIVE.

    Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_active_electronic_plate_count
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="ELECTRONIC", plate_number="ELEC-0101", activate_plate=True
    )
    validate_success(api_client.suspend_registration(reg["id"], ADMIN), 200)
    reg_susp = validate_success(api_client.get_registration(reg["id"], ADMIN), 200)
    reinstated = validate_success(
        api_client.reinstate_registration(
            reg["id"], {"expected_registration_version": reg_susp["version"]}, ADMIN
        ),
        200,
    )
    assert reinstated["status"] == "ACTIVE"
    plate_after = validate_success(api_client.get_license_plate(plate["id"], CLERK), 200)
    assert plate_after["status"] == "ACTIVE"


def test_reinstate_restores_registration_active():
    """PRD §3.8: "Reinstating a `SUSPENDED` registration, advancing it `SUSPENDED → ACTIVE` ...
    on success it transitions every electronic plate of that registration currently in status
    `DEACTIVATED` back to `ACTIVE`".

    The compensating pair returns the registration itself to ACTIVE, the precondition for the
    plate reactivation hop.

    Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_active_electronic_plate_count
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="ELECTRONIC", plate_number="ELEC-0102", activate_plate=True
    )
    validate_success(api_client.suspend_registration(reg["id"], ADMIN), 200)
    reg_susp = validate_success(api_client.get_registration(reg["id"], ADMIN), 200)
    reinstated = validate_success(
        api_client.reinstate_registration(
            reg["id"], {"expected_registration_version": reg_susp["version"]}, ADMIN
        ),
        200,
    )
    assert reinstated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/plate_number_tenancy_overlap_rejected
# ---------------------------------------------------------------------------
def test_plate_number_open_tenancy_reuse_rejected():
    """PRD §3.7: "A new assignment's tenancy must not overlap any existing plate row sharing the
    same `plate_number` whose interval is still open or has not yet closed before the new
    `issued_at`; reusing a `plate_number` whose prior tenancy was surrendered at or before the
    new `issued_at` is permitted ... A forbidden reuse is rejected with `ERR_PLATE_NUMBER_TAKEN`
    (HTTP 409)."

    Plate 'DUP-0001' issued to reg1 (open tenancy, surrendered_at null); assigning the same
    number to reg2 on a different vehicle is rejected.

    Design: Difficulty/resource_temporal_overlap/plate_number_tenancy_overlap_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    # Vehicle 1 -> ACTIVE reg + plate DUP-0001 (open tenancy).
    o1, v1, reg1 = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    assign_plate(reg1["id"], "DUP-0001", "PHYSICAL", reg1["version"])
    # Vehicle 2 -> ACTIVE reg ready for a plate.
    o2, v2, reg2 = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    resp = api_client.create_license_plate(
        {
            "registration_id": reg2["id"],
            "plate_number": "DUP-0001",
            "plate_type": "PHYSICAL",
            "expected_registration_version": reg2["version"],
        },
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_PLATE_NUMBER_TAKEN.value)


def test_plate_number_reuse_after_surrender_permitted():
    """PRD §3.7: "reusing a `plate_number` whose prior tenancy was surrendered at or before the
    new `issued_at` is permitted, with adjacency allowed at the surrender instant."

    After reg1 is expired (surrendering plate REUSE-1, closing its tenancy), the same number may
    be reissued to a second registration whose new issued_at is at/after the surrender instant.

    Design: Difficulty/resource_temporal_overlap/plate_number_tenancy_overlap_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    o1, v1, reg1 = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    assign_plate(reg1["id"], "REUSE-1", "PHYSICAL", reg1["version"])
    # Expire reg1 -> plate surrendered, tenancy closed.
    validate_success(api_client.expire_registration(reg1["id"], ADMIN), 200)
    # New vehicle/registration, clock advanced past the surrender instant.
    set_clock("2027-01-01T00:00:00Z")
    o2, v2, reg2 = setup_active_registration(model_year=2008, clock="2027-01-01T00:00:00Z")
    plate2 = validate_success(
        api_client.create_license_plate(
            {
                "registration_id": reg2["id"],
                "plate_number": "REUSE-1",
                "plate_type": "PHYSICAL",
                "expected_registration_version": reg2["version"],
            },
            CLERK,
        ),
        201,
    )
    assert plate2["plate_number"] == "REUSE-1"
    assert plate2["status"] == "ISSUED"


# ---------------------------------------------------------------------------
# Corner/state_machines/deactivate_physical_plate_rejected
# ---------------------------------------------------------------------------
def test_deactivate_physical_plate_rejected():
    """PRD §3.7: "An electronic plate may be remotely deactivated by a clerk, advancing it
    `ACTIVE → DEACTIVATED`, but only when its `plate_type` is `ELECTRONIC`; a deactivation
    attempt on a physical plate is rejected with `ERR_PLATE_NOT_ELECTRONIC` (HTTP 409)."

    Design: Corner/state_machines/deactivate_physical_plate_rejected
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="PHYSICAL", plate_number="PHYS-0214", activate_plate=True
    )
    resp = api_client.deactivate_license_plate(plate["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_PLATE_NOT_ELECTRONIC.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/activate_plate_registration_not_active_rejected
# ---------------------------------------------------------------------------
def test_activate_plate_on_suspended_registration_rejected():
    """PRD §3.7: "Once issued, a plate is activated by a clerk, advancing it `ISSUED → ACTIVE`,
    but only while its parent registration is in status `ACTIVE`; otherwise activation is
    rejected with `ERR_REGISTRATION_NOT_ACTIVE` (HTTP 409)."

    A plate left ISSUED on a now-SUSPENDED registration cannot be activated.

    Design: Corner/state_machines/activate_plate_registration_not_active_rejected
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="PHYSICAL", plate_number="PHYS-0215", activate_plate=False
    )
    validate_success(api_client.suspend_registration(reg["id"], ADMIN), 200)
    resp = api_client.activate_license_plate(plate["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/terminal_registration_expire_then_suspend_invalid
# ---------------------------------------------------------------------------
def test_suspend_after_expire_invalid_state():
    """PRD §3.8: "Suspending an `ACTIVE` registration, advancing it `ACTIVE → SUSPENDED` (the
    registration must be `ACTIVE`, otherwise `ERR_INVALID_STATE`, HTTP 409)".
    PRD §3.8: "Expiring an `ACTIVE` registration, advancing it `ACTIVE → EXPIRED` ... surrenders
    every plate of that registration in status `ISSUED`, `ACTIVE`, or `DEACTIVATED` by
    transitioning it to `SURRENDERED`".

    After EXPIRED (terminal), suspend fails ERR_INVALID_STATE and the plate is already
    SURRENDERED.

    Design: Corner/state_machines/terminal_registration_expire_then_suspend_invalid
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="PHYSICAL", plate_number="PHYS-0216", activate_plate=False
    )
    validate_success(api_client.expire_registration(reg["id"], ADMIN), 200)
    resp = api_client.suspend_registration(reg["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    plate_after = validate_success(api_client.get_license_plate(plate["id"], CLERK), 200)
    assert plate_after["status"] == "SURRENDERED"


# ---------------------------------------------------------------------------
# Corner/state_machines/expire_surrenders_all_plates_side_effect
# ---------------------------------------------------------------------------
def test_expire_surrenders_plate():
    """PRD §3.8: "Expiring an `ACTIVE` registration, advancing it `ACTIVE → EXPIRED` ...
    surrenders every plate of that registration in status `ISSUED`, `ACTIVE`, or `DEACTIVATED`
    by transitioning it to `SURRENDERED` and stamping its `surrendered_at` to the current clock".

    Design: Corner/state_machines/expire_surrenders_all_plates_side_effect
    """
    owner, veh, reg, plate = setup_active_registration_with_plate(
        plate_type="PHYSICAL", plate_number="PHYS-0217", activate_plate=True
    )
    expired = validate_success(api_client.expire_registration(reg["id"], ADMIN), 200)
    assert expired["status"] == "EXPIRED"
    plate_after = validate_success(api_client.get_license_plate(plate["id"], CLERK), 200)
    assert plate_after["status"] == "SURRENDERED"


# ---------------------------------------------------------------------------
# Corner/validations/plate_already_assigned_to_registration_rejected
# ---------------------------------------------------------------------------
def test_second_plate_on_registration_already_assigned_rejected():
    """PRD §3.7: "A registration may hold at most one plate in status `ISSUED`, `ACTIVE`, or
    `DEACTIVATED` at a time; an attempt to assign a second such plate to a registration that
    already has one is rejected with `ERR_PLATE_ALREADY_ASSIGNED` (HTTP 409)."

    Design: Corner/validations/plate_already_assigned_to_registration_rejected
    """
    owner, veh, reg = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    first = assign_plate(reg["id"], "FIRST-0230", "PHYSICAL", reg["version"])
    reg_after = validate_success(api_client.get_registration(reg["id"], CLERK), 200)
    resp = api_client.create_license_plate(
        {
            "registration_id": reg["id"],
            "plate_number": "SECOND-0230",
            "plate_type": "PHYSICAL",
            "expected_registration_version": reg_after["version"],
        },
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_PLATE_ALREADY_ASSIGNED.value)
