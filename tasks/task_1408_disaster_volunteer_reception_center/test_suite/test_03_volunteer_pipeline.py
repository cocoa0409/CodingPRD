"""Volunteer intake, credentialing, background checks, clearances, readiness."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_volunteer_payload, create_credential_payload,
    create_background_check_payload, create_clearance_payload,
    create_active_incident, register_volunteer, vet_volunteer, set_clock,
    make_vetting_headers, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
VET = TEST_USERS["vetting_headers"]
VET2 = TEST_USERS["vetting2_headers"] if "vetting2_headers" in TEST_USERS else None
RISK = TEST_USERS["risk_headers"]


def test_create_volunteer_missing_required_field_returns_invalid_request(api):
    """PRD section 2.11: "Request-body shape: required fields present, types
    correct, enum members valid, `quantity` and `headcount_needed` at least 1,
    hours positive, at most 16, and a multiple of 0.25, end instants strictly
    after start instants, the PPE stock object carrying exactly its five keys —
    any violation is `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/create_volunteer_missing_required_field_returns_invalid_request
    """
    incident = create_active_incident(name="Flood Upsilon",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    payload = create_volunteer_payload(incident["id"], full_name="No Phone")
    del payload["phone"]
    res = api.create_volunteer(payload, INTAKE)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_credential_with_invalid_enum_returns_invalid_request(api):
    """PRD section 3.2: "A claim names the `volunteer_id`, a `skill_code` drawn
    from `GENERAL_LABOR`, `CHAINSAW`, `MEDICAL`, `CDL`, `SHELTER_OPS`, and
    `TRANSLATION`, a `credential_class` of `STANDARD` or `ADVANCED`, a required
    `expires_at` marking the credential's expiry, and optional
    `evidence_notes` such as a license number or issuer"

    Design: Corner/entities/create_credential_with_invalid_enum_returns_invalid_request
    """
    incident = create_active_incident(name="Fire Phi",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Enum Test")
    res = api.create_credential(
        create_credential_payload(volunteer["id"], skill_code="DRIVING"), INTAKE)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_nonexistent_volunteer_returns_not_found(api):
    """PRD section 2.11: "Existence of every referenced resource: path
    identifiers are validated left to right, then body references in their
    declared input order, with the first miss yielding `ERR_RESOURCE_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_nonexistent_volunteer_returns_not_found
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.get_volunteer("11111111-2222-3333-4444-555555555555", MGR)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)


def test_system_and_computed_field_input_rejected(api):
    """PRD section 2.11: "any violation is `ERR_INVALID_REQUEST` (HTTP 400), as
    are an unknown payload field and a headcount edit below the current
    `filled_count`."

    Design: Corner/entities/system_and_computed_field_input_rejected
    """
    incident = create_active_incident(name="Fire Chi",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    payload = create_volunteer_payload(incident["id"], full_name="Sneaky Sam")
    payload["status"] = "READY"
    payload["committed_hours"] = 99.0
    res = api.create_volunteer(payload, INTAKE)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_new_records_start_in_initial_states(api):
    """PRD section 3.2: "Registration creates a volunteer in `REGISTERED`
    status from `incident_id`, `full_name`, `phone`, `email`, and
    `home_locality`"
    PRD section 3.3: "The request is born `DRAFT` with `filled_count` zero."
    PRD section 3.6: "The server records `reporter_user_id` from the caller and
    files the report as `FILED`."

    Design: Corner/state_machines/new_records_start_in_initial_states
    """
    from test_helpers import (create_support_request_payload, create_shift_payload,
                              create_risk_report_payload)
    AGENCY = TEST_USERS["agency_headers"]
    LOGI = TEST_USERS["logistics_headers"]
    SITE = TEST_USERS["supervisor_headers"]
    incident = create_active_incident(name="Fire C2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Vic Voss")
    assert volunteer["status"] == "REGISTERED"
    credential = validate_success(api.create_credential(
        create_credential_payload(volunteer["id"], skill_code="CDL",
                                  credential_class="ADVANCED"), INTAKE), 201)
    assert credential["status"] == "CLAIMED"
    validate_success(api.submit_for_vetting(volunteer["id"], INTAKE))
    check = validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    assert check["status"] == "REQUESTED"
    request = validate_success(api.create_support_request(
        create_support_request_payload(incident["id"], site_name="Yard",
                                       required_skill="CDL", min_credential_class="ADVANCED",
                                       criticality="CRITICAL"), AGENCY), 201)
    assert request["status"] == "DRAFT"
    shift = validate_success(api.create_shift(
        create_shift_payload(incident["id"], site_name="Yard", hazard_level="AMBER",
                             end_at="2026-08-10T12:00:00Z"), LOGI), 201)
    assert shift["status"] == "SCHEDULED"
    assert shift["duration_hours"] == 4.0
    report = validate_success(api.create_risk_report(
        create_risk_report_payload(volunteer["id"], description="minor"), SITE), 201)
    assert report["status"] == "FILED"


def test_submit_for_vetting_without_credentials_returns_no_credentials_claimed(api):
    """PRD section 3.2: "Submitting the volunteer for vetting, an
    `IntakeCoordinator` action, requires an `ACTIVE` incident and at least one
    credential record of any status — with zero claimed credentials the call
    fails with `ERR_NO_CREDENTIALS_CLAIMED` — and moves the volunteer from
    `REGISTERED` to `VETTING`."

    Design: Corner/validations/submit_for_vetting_without_credentials_returns_no_credentials_claimed
    """
    incident = create_active_incident(name="Flood E3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Xan Xie")
    res = api.submit_for_vetting(volunteer["id"], INTAKE)
    validate_error(res, "ERR_NO_CREDENTIALS_CLAIMED")


def test_volunteer_stays_vetting_until_background_check_cleared(api):
    """PRD section 3.2: "promotion from `VETTING` to `CLEARED` occurs as soon
    as the volunteer holds both a `CLEARED` background check whose `expires_at`
    is still in the future and at least one `VERIFIED` credential"

    Design: Difficulty/cross_entity_state_dependency/volunteer_not_cleared_until_background_check_cleared_then_flag_rejects
    """
    incident = create_active_incident(name="Fire Xi")
    volunteer = register_volunteer(incident["id"], full_name="Otto Orr")
    credential = validate_success(api.create_credential(
        create_credential_payload(volunteer["id"], skill_code="TRANSLATION"), INTAKE), 201)
    validate_success(api.submit_for_vetting(volunteer["id"], INTAKE))
    validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    validate_success(api.verify_credential(credential["id"], VET))
    mid = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert mid["status"] == "VETTING", (
        "VERIFIED credential alone must not promote; the background check is still REQUESTED")


def test_flagged_background_check_rejects_vetting_volunteer(api):
    """PRD section 3.2: "a `VETTING` volunteer is rejected outright into
    terminal `REJECTED`, while a `CLEARED`, `READY`, or `DEPLOYED` volunteer is
    suspended with the full suspension cascade of §3.6"

    Design: Difficulty/cross_entity_state_dependency/volunteer_not_cleared_until_background_check_cleared_then_flag_rejects
    """
    incident = create_active_incident(name="Fire Xi")
    volunteer = register_volunteer(incident["id"], full_name="Otto Orr")
    credential = validate_success(api.create_credential(
        create_credential_payload(volunteer["id"], skill_code="TRANSLATION"), INTAKE), 201)
    validate_success(api.submit_for_vetting(volunteer["id"], INTAKE))
    check = validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    validate_success(api.verify_credential(credential["id"], VET))
    validate_success(api.flag_background_check(check["id"], VET))
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["status"] == "REJECTED"


def test_clock_sweep_expires_credential_and_regresses_cleared_volunteer(api):
    """PRD section 3.2: "regression from `CLEARED` back to `VETTING` occurs
    automatically the moment that combination stops holding — for instance when
    the clock sweep expires the last cleared check or the last verified
    credential."

    Design: Corner/state_machines/clock_sweep_expires_credential_and_regresses_cleared_volunteer
    """
    incident = create_active_incident(name="Fire E2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Xu Xian")
    credential = validate_success(api.create_credential(
        create_credential_payload(volunteer["id"], skill_code="TRANSLATION",
                                  expires_at="2026-08-05T00:00:00Z"), INTAKE), 201)
    validate_success(api.submit_for_vetting(volunteer["id"], INTAKE))
    check = validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    validate_success(api.clear_background_check(check["id"], VET))
    verified = validate_success(api.verify_credential(credential["id"], VET))
    assert verified["status"] == "VERIFIED"
    mid = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert mid["status"] == "CLEARED"
    set_clock("2026-08-06T00:00:00Z")
    creds, _ = validate_paginated(api.list_volunteer_credentials(volunteer["id"], MGR))
    assert creds[0]["status"] == "EXPIRED"
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["status"] == "VETTING"


def test_second_pending_background_check_returns_already_pending(api):
    """PRD section 3.2: "A `VettingOfficer` then opens a background check,
    permitted only while the volunteer is `VETTING` or `SUSPENDED` and with at
    most one `REQUESTED` check per volunteer at a time; a second concurrent
    request fails with `ERR_CHECK_ALREADY_PENDING`."

    Design: Corner/validations/second_pending_background_check_returns_already_pending
    """
    incident = create_active_incident(name="Flood R2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Jay Joo")
    validate_success(api.create_credential(
        create_credential_payload(volunteer["id"], skill_code="MEDICAL",
                                  credential_class="ADVANCED"), INTAKE), 201)
    validate_success(api.submit_for_vetting(volunteer["id"], INTAKE))
    validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    res = api.create_background_check(create_background_check_payload(volunteer["id"]), VET)
    validate_error(res, "ERR_CHECK_ALREADY_PENDING")


def test_second_active_waiver_returns_clearance_already_active(api):
    """PRD section 3.2: "Only one `ACTIVE` clearance per type per volunteer may
    exist, and a duplicate attempt fails with `ERR_CLEARANCE_ALREADY_ACTIVE`."

    Design: Corner/validations/second_active_waiver_returns_clearance_already_active
    """
    incident = create_active_incident(name="Fire S2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    bundle = vet_volunteer(incident["id"], with_clearances=False, mark_ready=False,
                           full_name="Kay Kim")
    volunteer = bundle["volunteer"]
    validate_success(api.create_clearance(
        create_clearance_payload(volunteer["id"], "LIABILITY_WAIVER"), INTAKE), 201)
    res = api.create_clearance(
        create_clearance_payload(volunteer["id"], "LIABILITY_WAIVER"), INTAKE)
    validate_error(res, "ERR_CLEARANCE_ALREADY_ACTIVE")
    briefing = validate_success(api.create_clearance(
        create_clearance_payload(volunteer["id"], "SAFETY_BRIEFING"), INTAKE), 201)
    assert briefing["status"] == "ACTIVE"


def test_mark_ready_without_waiver_returns_readiness_incomplete(api):
    """PRD section 3.2: "Any missing item fails the call with
    `ERR_READINESS_INCOMPLETE`, whose message names each missing item; success
    moves the volunteer from `CLEARED` to `READY`."

    Design: Corner/validations/mark_ready_without_waiver_returns_readiness_incomplete
    """
    incident = create_active_incident(name="Fire D3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    bundle = vet_volunteer(incident["id"], with_clearances=False, mark_ready=False,
                           full_name="Wanda Wex")
    volunteer = bundle["volunteer"]
    validate_success(api.create_clearance(
        create_clearance_payload(volunteer["id"], "SAFETY_BRIEFING"), INTAKE), 201)
    res = api.mark_ready(volunteer["id"], INTAKE)
    error = validate_error(res, "ERR_READINESS_INCOMPLETE")
    assert "LIABILITY_WAIVER" in error["message"], (
        f"message must name the missing waiver, got {error['message']!r}")


def test_waiver_revocation_regresses_ready_volunteer_to_cleared(api):
    """PRD section 3.6: "revoking a liability waiver while the volunteer is
    `READY` regresses them to `CLEARED`, while revoking it during `DEPLOYED`
    suspends them with the full cascade above, and revoking a briefing carries
    no volunteer-level consequence."

    Design: Corner/state_machines/waiver_revocation_regresses_ready_volunteer_to_cleared
    """
    incident = create_active_incident(name="Flood H2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    bundle = vet_volunteer(incident["id"], full_name="Amy Aoki")
    volunteer = bundle["volunteer"]
    assert volunteer["status"] == "READY"
    revoked = validate_success(api.revoke_clearance(
        bundle["waiver"]["id"], {"reason": "volunteer repudiated signature"}, RISK))
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_reason"] == "volunteer repudiated signature"
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["status"] == "CLEARED"
