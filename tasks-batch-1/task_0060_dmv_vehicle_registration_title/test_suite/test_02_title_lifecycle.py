"""Title application lifecycle: clear/salvage fork, brand stamping, submit/approve gates."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    create_owner,
    create_vehicle,
    create_verified_vehicle,
    create_vin_verification_payload,
    create_title_application_payload,
    create_salvage_inspection_payload,
    create_salvage_hold_title,
    create_approved_title,
    issue_clear_title,
)

CLERK = TEST_USERS["clerk_headers"]
INSPECTION = TEST_USERS["inspection_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/title_brand_clear_vs_rebuilt_on_issue
# ---------------------------------------------------------------------------
def test_issue_ordinary_application_stamps_clear_brand():
    """PRD §3.2: "First, the application's `issued_title_brand` is stamped: `REBUILT` if the
    application required the salvage path, and `CLEAR` otherwise. Second, as a direct
    consequence of issuance, the subject vehicle's `title_status` is set to match — `REBUILT`
    if the salvage path was required, `CLEAR` otherwise".

    A non-salvage application issues issued_title_brand CLEAR and vehicle.title_status CLEAR.

    Design: Difficulty/dual_variant_calc/title_brand_clear_vs_rebuilt_on_issue
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"], is_salvage_branded=False)
    ta = create_approved_title(veh["id"], owner["id"], "INITIAL")
    issued = validate_success(api_client.issue_title_application(ta["id"], CLERK), 200)
    assert issued["issued_title_brand"] == "CLEAR"
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert veh_after["title_status"] == "CLEAR"


def test_issue_salvage_application_stamps_rebuilt_brand():
    """PRD §3.2: "First, the application's `issued_title_brand` is stamped: `REBUILT` if the
    application required the salvage path, and `CLEAR` otherwise. Second, as a direct
    consequence of issuance, the subject vehicle's `title_status` is set to match — `REBUILT`
    if the salvage path was required, `CLEAR` otherwise".

    A salvage-branded application that passed rebuild inspection issues issued_title_brand
    REBUILT and vehicle.title_status REBUILT.

    Design: Difficulty/dual_variant_calc/title_brand_clear_vs_rebuilt_on_issue
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"], is_salvage_branded=True)
    ta = create_salvage_hold_title(veh["id"], owner["id"])
    validate_success(
        api_client.create_salvage_inspection(
            create_salvage_inspection_payload(ta["id"], "PASS"), INSPECTION
        ),
        201,
    )
    validate_success(api_client.approve_title_application(ta["id"], CLERK), 200)
    issued = validate_success(api_client.issue_title_application(ta["id"], CLERK), 200)
    assert issued["issued_title_brand"] == "REBUILT"
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert veh_after["title_status"] == "REBUILT"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/title_application_branch_fork_salvage_hold
# ---------------------------------------------------------------------------
def test_submit_salvage_branded_forks_to_salvage_hold():
    """PRD §3.2: "On a successful submit, the application's `requires_salvage_path` is set to
    the vehicle's `is_salvage_branded` flag. Here the path forks: if the vehicle is
    salvage-branded, the application moves to `SALVAGE_HOLD` rather than `SUBMITTED`; otherwise
    it advances to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/title_application_branch_fork_salvage_hold
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"], is_salvage_branded=True)
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], owner["id"], "INITIAL"), CLERK
        ),
        201,
    )
    submitted = validate_success(api_client.submit_title_application(ta["id"], CLERK), 200)
    assert submitted["status"] == "SALVAGE_HOLD"
    assert submitted["requires_salvage_path"] is True


def test_submit_ordinary_vehicle_advances_to_submitted():
    """PRD §3.2: "Here the path forks: if the vehicle is salvage-branded, the application moves
    to `SALVAGE_HOLD` rather than `SUBMITTED`; otherwise it advances to `SUBMITTED`."

    A non-salvage vehicle takes the non-fork branch: submit -> SUBMITTED, requires_salvage_path
    false.

    Design: Difficulty/non_linear_state_machine/title_application_branch_fork_salvage_hold
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"], is_salvage_branded=False)
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], owner["id"], "INITIAL"), CLERK
        ),
        201,
    )
    submitted = validate_success(api_client.submit_title_application(ta["id"], CLERK), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["requires_salvage_path"] is False


# ---------------------------------------------------------------------------
# Corner/state_machines/approve_title_application_from_draft_invalid_state
# ---------------------------------------------------------------------------
def test_approve_draft_application_invalid_state():
    """PRD §3.2: "From `SUBMITTED`, a clerk may approve the application, advancing it
    `SUBMITTED → APPROVED` ... each requires the application to actually be in `SUBMITTED`
    (otherwise `ERR_INVALID_STATE`, HTTP 409)."

    A DRAFT (never-submitted) application cannot be approved.

    Design: Corner/state_machines/approve_title_application_from_draft_invalid_state
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"])
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], owner["id"], "INITIAL"), CLERK
        ),
        201,
    )
    resp = api_client.approve_title_application(ta["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/submit_title_application_vin_unverified_rejected
# ---------------------------------------------------------------------------
def test_submit_unverified_vin_rejected():
    """PRD §3.2: "A clerk may submit only after the subject vehicle's `vin_status` is
    `VERIFIED`; otherwise submission is rejected with `ERR_VIN_NOT_VERIFIED` (HTTP 409)."

    Design: Corner/state_machines/submit_title_application_vin_unverified_rejected
    """
    owner = create_owner()
    veh = create_vehicle(owner_id=owner["id"])  # never VIN-verified
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], owner["id"], "INITIAL"), CLERK
        ),
        201,
    )
    resp = api_client.submit_title_application(ta["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_VIN_NOT_VERIFIED.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/transfer_title_without_existing_title_rejected
# ---------------------------------------------------------------------------
def test_submit_transfer_without_existing_title_rejected():
    """PRD §3.2: "Additionally, when the `application_type` is `TRANSFER`, the subject vehicle
    must already hold a title — its `title_status` must be one of `CLEAR` or `REBUILT` — or
    submission is rejected with `ERR_TRANSFER_REQUIRES_TITLE` (HTTP 409)."

    Design: Corner/state_machines/transfer_title_without_existing_title_rejected
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"])  # title_status NONE
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], owner["id"], "TRANSFER"), CLERK
        ),
        201,
    )
    resp = api_client.submit_title_application(ta["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_REQUIRES_TITLE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/approve_salvage_hold_without_passing_inspection_rejected
# ---------------------------------------------------------------------------
def test_approve_salvage_hold_without_passing_inspection_rejected():
    """PRD §3.2: "A clerk may approve a salvage-hold application, advancing it
    `SALVAGE_HOLD → APPROVED`, only when a `SalvageInspection` exists for that application with
    `result` of `PASS`; absent such a passing inspection, approval is rejected with
    `ERR_SALVAGE_INSPECTION_REQUIRED` (HTTP 409)."

    Design: Corner/state_machines/approve_salvage_hold_without_passing_inspection_rejected
    """
    owner = create_owner()
    veh = create_verified_vehicle(owner_id=owner["id"], is_salvage_branded=True)
    ta = create_salvage_hold_title(veh["id"], owner["id"])  # no inspection filed
    resp = api_client.approve_title_application(ta["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_SALVAGE_INSPECTION_REQUIRED.value)
