"""REAL ID review cycle and optimistic-concurrency (OCC) version guards."""
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
    setup_real_id_under_review,
    create_real_id_application_payload,
    create_vin_verification_payload,
    create_vehicle,
)

CLERK = TEST_USERS["clerk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/real_id_application_review_revert_cycle
# ---------------------------------------------------------------------------
def test_real_id_return_for_documents_reverts_to_submitted():
    """PRD §3.6: "Returning the application for more documents, advancing it
    `UNDER_REVIEW → SUBMITTED` (otherwise `ERR_INVALID_STATE`), likewise sets the owner's
    `real_id_status` back to `NONE` and increments `Owner.version` by 1; this is the revert
    cycle that lets review bounce back to intake for a more complete document set."

    Design: Difficulty/non_linear_state_machine/real_id_application_review_revert_cycle
    """
    owner, rid = setup_real_id_under_review(identity_verified=True, documents_complete=True)
    returned = validate_success(api_client.return_real_id_application(rid["id"], CLERK), 200)
    assert returned["status"] == "SUBMITTED"


def test_real_id_review_cycle_repeats_to_under_review():
    """PRD §3.6: "A clerk begins review of a `SUBMITTED` application, advancing it
    `SUBMITTED → UNDER_REVIEW`; this requires the application to be in `SUBMITTED` ... and sets
    the owner's `real_id_status` to `PENDING`, incrementing the affected `Owner.version` by 1."

    The A->B->A cycle: after return-for-documents bounces back to SUBMITTED, begin-review can run
    again, landing UNDER_REVIEW and setting the owner's real_id_status PENDING once more.

    Design: Difficulty/non_linear_state_machine/real_id_application_review_revert_cycle
    """
    owner, rid = setup_real_id_under_review(identity_verified=True, documents_complete=True)
    validate_success(api_client.return_real_id_application(rid["id"], CLERK), 200)
    second = validate_success(api_client.begin_review_real_id_application(rid["id"], CLERK), 200)
    assert second["status"] == "UNDER_REVIEW"
    owner_after = validate_success(api_client.get_owner(owner["id"], CLERK), 200)
    assert owner_after["real_id_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner/state_machines/real_id_approve_documents_incomplete_rejected
# ---------------------------------------------------------------------------
def test_real_id_approve_documents_incomplete_rejected():
    """PRD §3.6: "Approving the upgrade, advancing it `UNDER_REVIEW → APPROVED`, requires that
    the application's `documents_complete` is true and the owner's `identity_documents_verified`
    is true; if either is false, approval is rejected with `ERR_DOCUMENTS_INCOMPLETE` (HTTP 409)."

    Design: Corner/state_machines/real_id_approve_documents_incomplete_rejected
    """
    owner, rid = setup_real_id_under_review(identity_verified=True, documents_complete=False)
    resp = api_client.approve_real_id_application(rid["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/real_id_approve_sets_owner_credential_real_id
# ---------------------------------------------------------------------------
def test_real_id_approve_upgrades_owner_credential():
    """PRD §3.6: "A successful approval sets the owner's `credential_type` to `REAL_ID` and the
    owner's `real_id_status` to `UPGRADED`, incrementing `Owner.version` by 1."

    Design: Corner/state_machines/real_id_approve_sets_owner_credential_real_id
    """
    owner, rid = setup_real_id_under_review(identity_verified=True, documents_complete=True)
    validate_success(api_client.approve_real_id_application(rid["id"], CLERK), 200)
    owner_after = validate_success(api_client.get_owner(owner["id"], CLERK), 200)
    assert owner_after["credential_type"] == "REAL_ID"
    assert owner_after["real_id_status"] == "UPGRADED"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_plate_assign_stale_version_rejected
# ---------------------------------------------------------------------------
def test_plate_assign_stale_registration_version_rejected():
    """PRD §2.7: "a request to assign a license plate to a registration must carry
    `expected_registration_version` matching the target registration's current `version`. If
    another writer has already advanced the registration's `version` since the client last read
    it — for instance by assigning the registration's single plate — the assignment is rejected
    with `ERR_STALE_VERSION` (HTTP 412)".

    A first plate assignment bumps the registration version; a second assignment carrying the
    pre-assignment version is stale. (The first plate is surrendered via expire so the
    one-plate-per-registration rule does not pre-empt the version check.)

    Design: Corner/cross_cutting_complexity_layers/occ_plate_assign_stale_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    owner, veh, reg = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    stale_version = reg["version"]
    assign_plate(reg["id"], "OCC-0272A", "PHYSICAL", stale_version)
    validate_success(api_client.expire_registration(reg["id"], ADMIN), 200)
    resp = api_client.create_license_plate(
        {
            "registration_id": reg["id"],
            "plate_number": "OCC-0272B",
            "plate_type": "PHYSICAL",
            "expected_registration_version": stale_version,
        },
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_reinstate_stale_version_rejected
# ---------------------------------------------------------------------------
def test_reinstate_stale_registration_version_rejected():
    """PRD §2.7: "The second guarded operation is reinstatement of a suspended registration:
    that request must likewise carry `expected_registration_version` matching the registration's
    current `version`, and if a prior reinstatement has already advanced the `version` and
    reactivated the electronic plates, the stale caller's reinstatement is refused with
    `ERR_STALE_VERSION` (HTTP 412)."

    The suspend bumps the version past the value captured while ACTIVE; reinstating with that
    stale ACTIVE-era version is refused.

    Design: Corner/cross_cutting_complexity_layers/occ_reinstate_stale_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    owner, veh, reg = setup_active_registration(model_year=2008, clock="2026-06-01T00:00:00Z")
    reg_active = validate_success(api_client.get_registration(reg["id"], ADMIN), 200)
    stale_active_version = reg_active["version"]
    validate_success(api_client.suspend_registration(reg["id"], ADMIN), 200)
    resp = api_client.reinstate_registration(
        reg["id"], {"expected_registration_version": stale_active_version}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/version_increments_on_vin_verification
# ---------------------------------------------------------------------------
def test_vin_verification_increments_vehicle_version():
    """PRD §3.1: "Recording a verification increments the affected `Vehicle.version` by 1."
    PRD §2.4: "an integer `version` that begins at 1 on creation and increments by exactly 1 on
    each mutation."

    A freshly created vehicle (version 1) advances to version 2 after one VIN verification, and
    its vin_status becomes VERIFIED.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_vin_verification
    """
    owner = create_owner()
    veh = create_vehicle(owner_id=owner["id"])
    assert veh["version"] == 1
    validate_success(
        api_client.create_vin_verification(
            create_vin_verification_payload(veh["id"], veh["vin"], "MATCH"), CLERK
        ),
        201,
    )
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert veh_after["version"] == 2
    assert veh_after["vin_status"] == "VERIFIED"
