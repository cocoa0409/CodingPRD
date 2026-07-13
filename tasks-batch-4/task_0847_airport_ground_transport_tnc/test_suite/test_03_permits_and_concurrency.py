"""Permit issuance, the decal lifecycle, and optimistic concurrency on Vehicle.version."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_permit_payload,
    TEST_USERS,
    set_clock, create_operator, register_vehicle, issue_permit,
)

AA = TEST_USERS["airport_authority_headers"]


def test_permit_activate_mints_decal_number(api):
    """PRD §3.2: "A newly issued permit begins in `permit_status` `ISSUED` with a
    null `decal_number` and null `suspended_reason`; the act of issuance increments
    the owning vehicle's `version` by one."
    PRD §3.2: "Activating an `ISSUED` permit (`ISSUED → ACTIVE`) is permitted only
    while the logical clock lies within the validity window — at or after
    `valid_from` and strictly before `valid_until` — and, on success, mints and
    assigns the physical `decal_number` serial."

    Design: Corner/state_machines/permit_activate_mints_decal_number
    """
    set_clock(api, "2026-03-20T00:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Dec Co")
    veh = register_vehicle(api, op["id"], plate="DCV1")
    permit = issue_permit(api, veh["id"], veh["version"], avi_tag_id="AVI-DCV1")
    assert permit["permit_status"] == "ISSUED"
    assert permit["decal_number"] is None, "decal_number must be null while ISSUED"
    activated = validate_success(
        api.transition_permit(permit["id"], {"action": "ACTIVATE"}, AA)
    )
    assert activated["permit_status"] == "ACTIVE"
    assert activated["decal_number"] is not None, "decal_number must be minted on activation"


def test_duplicate_avi_tag_rejected(api):
    """PRD §3.2: "The `avi_tag_id` must be globally unique across live permits: if
    the supplied tag is already held by another permit whose `permit_status` is
    `ISSUED`, `ACTIVE`, or `SUSPENDED`, the issuance is rejected with
    `ERR_DUPLICATE_AVI_TAG`."

    Design: Corner/validations/duplicate_avi_tag_returns_conflict
    """
    op = create_operator(api, operator_type="TNC", legal_name="Dup Co")
    veh1 = register_vehicle(api, op["id"], plate="DUP1")
    issue_permit(api, veh1["id"], veh1["version"], avi_tag_id="AVI-DUP")  # ISSUED, live
    veh2 = register_vehicle(api, op["id"], plate="DUP2")
    resp = api.create_permit(
        create_permit_payload(veh2["id"], veh2["version"], avi_tag_id="AVI-DUP"), AA
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_AVI_TAG.value, 409)


def test_permit_issue_stale_vehicle_version_rejected(api):
    """PRD §2.7: "If that value does not equal the vehicle's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a successful
    permit issuance increments the owning vehicle's `version` by one, a client
    whose view of the vehicle has gone stale — because another issuance has already
    advanced the vehicle's `version` since it last read the vehicle — is rejected on
    this check rather than silently minting a second, superseding credential against
    a vehicle it has not re-observed."

    Design: Corner/cross_cutting_complexity_layers/permit_issue_stale_vehicle_version_returns_stale
    """
    op = create_operator(api, operator_type="TNC", legal_name="OCC Co")
    veh = register_vehicle(api, op["id"], plate="OCCV1")
    stale_version = veh["version"]
    issue_permit(api, veh["id"], stale_version, avi_tag_id="AVI-OCC1")  # advances version
    resp = api.create_permit(
        create_permit_payload(veh["id"], stale_version, avi_tag_id="AVI-OCC2"), AA
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_permit_issue_correct_version_increments_vehicle_version(api):
    """PRD §2.7: "Because a successful permit issuance increments the owning
    vehicle's `version` by one, a client whose view of the vehicle has gone stale
    — because another issuance has already advanced the vehicle's `version` since it
    last read the vehicle — is rejected on this check rather than silently minting a
    second, superseding credential against a vehicle it has not re-observed."

    Design: Corner/cross_cutting_complexity_layers/permit_issue_correct_version_increments_vehicle_version
    """
    op = create_operator(api, operator_type="TNC", legal_name="OCC2 Co")
    veh = register_vehicle(api, op["id"], plate="OCCV2")
    assert veh["version"] == 1
    issue_permit(api, veh["id"], veh["version"], avi_tag_id="AVI-OCC3")
    refreshed = validate_success(api.get_vehicle(veh["id"], AA))
    assert refreshed["version"] == 2, f"expected version 2 after issuance, got {refreshed['version']}"
